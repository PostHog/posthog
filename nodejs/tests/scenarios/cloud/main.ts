import { EXIT_CODE } from '../runner/status'
import { Controller, admit, refuseOutsideDev } from './admission'
import { awsCli } from './aws'
import { lease, manifestOf, release, sweepExpired } from './lease'
import { githubOrigin } from './origin'
import { CloudProfile, REGION, RunInputs, loadCloudProfile, loadRunInputs } from './profile'

export type { Controller } from './admission'

const USAGE = [
    'Usage:',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts run <cloud profile>',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> (<run id> | --expired)',
].join('\n')

function defaultController(): Controller {
    return {
        aws: awsCli({ ...process.env, AWS_REGION: REGION, AWS_PAGER: '' }),
        origin: githubOrigin(),
        now: () => new Date(),
        env: process.env,
        print: (line) => process.stdout.write(`${line}\n`),
        warn: (line) => process.stderr.write(`${line}\n`),
    }
}

async function run(controller: Controller, loaded: RunInputs): Promise<number> {
    const bucket = loaded.profile.baseline.evidenceBucket
    for (const problem of await sweepExpired(controller, bucket)) {
        controller.warn(problem)
    }
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

async function cleanup(controller: Controller, profile: CloudProfile, target: string): Promise<number> {
    const bucket = profile.baseline.evidenceBucket
    if (target === '--expired') {
        const problems = await sweepExpired(controller, bucket)
        problems.forEach((problem) => controller.warn(problem))
        return problems.length > 0 ? EXIT_CODE.invalid : EXIT_CODE.passed
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
        await refuseOutsideDev(controller, loadCloudProfile(file).account)
        return command === 'run'
            ? await run(controller, loadRunInputs(file))
            : await cleanup(controller, loadCloudProfile(file), target)
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
