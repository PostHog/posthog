import { execFile } from 'child_process'

import { parseJSON } from '~/common/utils/json-parse'

export type Aws = {
    call(args: string[]): Promise<unknown>
    text(args: string[]): Promise<string>
}

const OUTPUT_LIMIT_BYTES = 256 * 1024 * 1024
const NOT_INSTALLED = 127

export class AwsError extends Error {
    readonly code: string | undefined

    constructor(
        readonly args: string[],
        readonly exitCode: number,
        readonly stderr: string
    ) {
        super(`aws ${args.slice(0, 2).join(' ')} exited ${exitCode}: ${stderr.trim()}`)
        this.name = 'AwsError'
        this.code = /An error occurred \(([^)]+)\)/.exec(stderr)?.[1]
    }
}

function retriesOf(args: string[]): NodeJS.ProcessEnv {
    // A retried failover after a lost response would promote a second time, so the CLI gets one attempt.
    return args[1] === 'failover-db-cluster' ? { AWS_MAX_ATTEMPTS: '1' } : {}
}

export function awsCli(env: NodeJS.ProcessEnv): Aws {
    const run = (args: string[]): Promise<string> =>
        new Promise((resolve, reject) =>
            execFile(
                'aws',
                args,
                { env: { ...env, ...retriesOf(args) }, maxBuffer: OUTPUT_LIMIT_BYTES },
                (error, stdout, stderr) => {
                    if (!error) {
                        resolve(stdout)
                    } else if (typeof error.code === 'number') {
                        reject(new AwsError(args, error.code, stderr))
                    } else {
                        reject(new AwsError(args, NOT_INSTALLED, `the aws CLI could not start: ${error.message}`))
                    }
                }
            )
        )
    return {
        call: async (args) => {
            const stdout = await run([...args, '--output', 'json'])
            return stdout.trim() === '' ? null : parseJSON(stdout)
        },
        text: async (args) => (await run(args)).trim(),
    }
}
