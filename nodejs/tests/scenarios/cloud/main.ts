import { EXIT_CODE } from '../runner/status'
import { Controller, admit, refuseOutsideDev } from './admission'
import { awsCli } from './aws'
import { isCardId, runCardOf } from './card'
import { awaitCard, prepareDatabase, startCard } from './host'
import { lease, manifestOf } from './lease'
import { githubOrigin } from './origin'
import { CloudProfile, ProfileInputs, REGION, loadCloudProfile, loadRunInputs } from './profile'
import { report } from './report'
import { addReader, createRunStack } from './stack'
import { teardown } from './teardown'

export type { Controller } from './admission'

const USAGE = [
    'Usage:',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts run <cloud profile> <card id>',
    '  pnpm --dir nodejs exec tsx tests/scenarios/cloud/main.ts cleanup <cloud profile> <run id>',
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

async function run(controller: Controller, inputs: ProfileInputs, cardId: string): Promise<number> {
    const { profile } = inputs
    const { min, max, idleMax } = profile.readerAcu
    if (idleMax !== undefined && idleMax < min) {
        throw new Error(`readerAcu.idleMax ${idleMax} is under readerAcu.min ${min}, so no reader could pass it.`)
    }
    if (idleMax !== undefined && idleMax >= max) {
        throw new Error(
            `readerAcu.idleMax ${idleMax} is not under readerAcu.max ${max}, so every reader would pass it.`
        )
    }
    const admission = await admit(controller, profile)
    if ('problems' in admission) {
        controller.warn(`Refused the run:\n${admission.problems.map((problem) => `- ${problem}`).join('\n')}`)
        return EXIT_CODE.invalid
    }
    const card = runCardOf(controller.origin, admission.admitted.commit, cardId, inputs.runner.bytes)
    if (card.failsOver && profile.readerAcu.idleMax === undefined) {
        throw new Error(`${cardId} fails the reader over, so the cloud profile needs readerAcu.idleMax.`)
    }
    const loaded = { ...inputs, card }
    const manifest = await lease(controller, loaded, admission.admitted)
    controller.print(`Leased run ${manifest.runId} until ${manifest.expiresAt}.`)
    const interruption = new AbortController()
    const stopListening = controller.onInterrupt(() => {
        controller.warn(`Interrupted; tearing down run ${manifest.runId}.`)
        interruption.abort()
    })
    let outcome: number = EXIT_CODE.passed
    const reasons: string[] = []
    let teardownClean = false
    try {
        const parameters = await createRunStack(controller, profile, manifest, interruption.signal)
        await prepareDatabase(controller, profile, manifest, interruption.signal)
        await addReader(controller, profile, manifest, parameters, interruption.signal)
        await startCard(controller, profile, manifest, interruption.signal)
        outcome = await awaitCard(controller, profile, manifest, interruption.signal)
    } catch (error) {
        controller.warn(`Run ${manifest.runId} is invalid: ${(error as Error).message}`)
        reasons.push((error as Error).message)
        outcome = EXIT_CODE.invalid
    } finally {
        teardownClean = await teardown(controller, profile, manifest)
        if (!teardownClean) {
            reasons.push('teardown did not confirm that the run left nothing behind')
            outcome = EXIT_CODE.invalid
        }
        stopListening()
    }
    return await report(controller, loaded, manifest, { exitCode: outcome, reasons, teardownClean })
}

async function cleanup(controller: Controller, profile: CloudProfile, target: string): Promise<number> {
    const clean = await teardown(
        controller,
        profile,
        await manifestOf(controller, profile.baseline.evidenceBucket, target)
    )
    return clean ? EXIT_CODE.passed : EXIT_CODE.invalid
}

export async function main(argv: string[], controller: Controller = defaultController()): Promise<number> {
    const [command, file, target, ...rest] = argv
    const usable = ['run', 'cleanup'].includes(command) && file && target && rest.length === 0
    if (!usable) {
        controller.warn(USAGE)
        return EXIT_CODE.invalid
    }
    try {
        if (command === 'run' && !isCardId(target)) {
            throw new Error(
                `${target} is not a card id. The run host runs the cards of the run's commit, so name one under tests/scenarios/cards.`
            )
        }
        const loaded = command === 'run' ? loadRunInputs(file) : undefined
        const profile = loaded?.profile ?? loadCloudProfile(file)
        await refuseOutsideDev(controller, profile.account)
        return loaded ? await run(controller, loaded, target) : await cleanup(controller, profile, target)
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
