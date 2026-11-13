import { execFileSync } from 'child_process'
import os from 'os'

import { internalFetch } from '~/common/utils/request'

import { EXIT_CODE } from '../runner/status'
import { Controller, Origin, admit } from './admission'
import { awsCli } from './aws'
import { lease, manifestOf, release, sweepExpired } from './lease'
import { LoadedCloudProfile, REGION, loadCloudProfile } from './profile'

export type { Controller } from './admission'

const USAGE = [
    'Usage:',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts run <cloud profile>',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> (<run id> | --expired)',
].join('\n')
const REPOSITORY = 'PostHog/posthog'
const REQUEST_TIMEOUT_MS = 10_000

function githubOrigin(): Origin {
    return {
        head: () => execFileSync('git', ['rev-parse', 'HEAD'], { cwd: __dirname, encoding: 'utf8' }).trim(),
        published: async (commit) => {
            const response = await internalFetch(`https://api.github.com/repos/${REPOSITORY}/commits/${commit}`, {
                headers: { Accept: 'application/vnd.github+json' },
                timeoutMs: REQUEST_TIMEOUT_MS,
            })
            if (response.status === 404 || response.status === 422) {
                return false
            }
            if (response.status !== 200) {
                throw new Error(`GitHub answered ${response.status} for commit ${commit}`)
            }
            return true
        },
    }
}

function defaultController(): Controller {
    return {
        aws: awsCli({ ...process.env, AWS_REGION: REGION, AWS_PAGER: '' }),
        origin: githubOrigin(),
        now: () => new Date(),
        home: os.homedir(),
        print: (line) => process.stdout.write(`${line}\n`),
        warn: (line) => process.stderr.write(`${line}\n`),
    }
}

async function run(controller: Controller, loaded: LoadedCloudProfile): Promise<number> {
    const bucket = loaded.profile.baseline.evidenceBucket
    await sweepExpired(controller, bucket)
    const admission = await admit(controller, loaded.profile)
    if ('problems' in admission) {
        controller.warn(`Refused the run:\n${admission.problems.map((problem) => `- ${problem}`).join('\n')}`)
        return EXIT_CODE.invalid
    }
    const manifest = await lease(controller, loaded, admission.admitted)
    try {
        controller.print(`Leased run ${manifest.runId} until ${manifest.expiresAt}.`)
    } finally {
        await release(controller, bucket, manifest)
    }
    return EXIT_CODE.passed
}

async function cleanup(controller: Controller, { profile }: LoadedCloudProfile, target: string): Promise<number> {
    const bucket = profile.baseline.evidenceBucket
    if (target === '--expired') {
        await sweepExpired(controller, bucket)
    } else {
        await release(controller, bucket, await manifestOf(controller, bucket, target))
    }
    return EXIT_CODE.passed
}

export async function main(argv: string[], controller: Controller = defaultController()): Promise<number> {
    const [command, file, target, ...rest] = argv
    const usable =
        (command === 'run' && file && !target) || (command === 'cleanup' && file && target && rest.length === 0)
    if (!usable) {
        controller.warn(USAGE)
        return EXIT_CODE.invalid
    }
    try {
        const loaded = loadCloudProfile(file)
        return command === 'run' ? await run(controller, loaded) : await cleanup(controller, loaded, target)
    } catch (error) {
        controller.warn((error as Error).message)
        return EXIT_CODE.invalid
    }
}

if (require.main === module) {
    void main(process.argv.slice(2)).then(
        (code) => process.exit(code),
        (error: unknown) => {
            process.stderr.write(`${String(error)}\n`)
            process.exit(EXIT_CODE.invalid)
        }
    )
}
