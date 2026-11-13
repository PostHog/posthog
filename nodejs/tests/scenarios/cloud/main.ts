import { EXIT_CODE } from '../runner/status'
import { Controller, admit, refuseOutsideDev } from './admission'
import { awsCli } from './aws'
import { awaitCard, prepareDatabase, startCard } from './host'
import { lease, manifestOf } from './lease'
import { githubOrigin } from './origin'
import { CloudProfile, REGION, RunInputs, loadCloudProfile, loadRunInputs } from './profile'
import { addReader, createRunStack } from './stack'
import { teardown, teardownExpired } from './teardown'

export type { Controller } from './admission'

const USAGE = [
    'Usage:',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts run <cloud profile>',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> (<run id> | --expired)',
].join('\n')

const SIGNALS: NodeJS.Signals[] = ['SIGINT', 'SIGTERM']

function defaultController(): Controller {
    return {
        aws: awsCli({ ...process.env, AWS_REGION: REGION, AWS_PAGER: '' }),
        origin: githubOrigin(),
        now: () => new Date(),
        sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
        onInterrupt: (handler) => {
            SIGNALS.forEach((signal) => process.on(signal, handler))
            return () => SIGNALS.forEach((signal) => process.off(signal, handler))
        },
        env: process.env,
        print: (line) => process.stdout.write(`${line}\n`),
        warn: (line) => process.stderr.write(`${line}\n`),
    }
}

async function run(controller: Controller, loaded: RunInputs): Promise<number> {
    const { profile } = loaded
    if (!(await teardownExpired(controller, profile, { retryLeftovers: false }))) {
        controller.warn('Refused the run: an expired run still holds resources.')
        return EXIT_CODE.invalid
    }
    const admission = await admit(controller, profile)
    if ('problems' in admission) {
        controller.warn(`Refused the run:\n${admission.problems.map((problem) => `- ${problem}`).join('\n')}`)
        return EXIT_CODE.invalid
    }
    const manifest = await lease(controller, loaded, admission.admitted)
    controller.print(`Leased run ${manifest.runId} until ${manifest.expiresAt}.`)
    const interruption = new AbortController()
    const stopListening = controller.onInterrupt(() => {
        controller.warn(`Interrupted; tearing down run ${manifest.runId}.`)
        interruption.abort()
    })
    let outcome: number = EXIT_CODE.passed
    try {
        const parameters = await createRunStack(controller, profile, manifest, interruption.signal)
        await prepareDatabase(controller, profile, manifest, interruption.signal)
        await addReader(controller, profile, manifest, parameters, interruption.signal)
        await startCard(controller, profile, manifest, interruption.signal)
        outcome = await awaitCard(controller, profile, manifest, interruption.signal)
    } catch (error) {
        controller.warn(`Run ${manifest.runId} is invalid: ${(error as Error).message}`)
        outcome = EXIT_CODE.invalid
    } finally {
        if (!(await teardown(controller, profile, manifest))) {
            outcome = EXIT_CODE.invalid
        }
        stopListening()
    }
    return outcome
}

async function cleanup(controller: Controller, profile: CloudProfile, target: string): Promise<number> {
    const clean =
        target === '--expired'
            ? await teardownExpired(controller, profile, { retryLeftovers: true })
            : await teardown(controller, profile, await manifestOf(controller, profile.baseline.evidenceBucket, target))
    return clean ? EXIT_CODE.passed : EXIT_CODE.invalid
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
        const loaded = command === 'run' ? loadRunInputs(file) : undefined
        const profile = loaded?.profile ?? loadCloudProfile(file)
        await refuseOutsideDev(controller, profile.account)
        return loaded ? await run(controller, loaded) : await cleanup(controller, profile, target)
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
