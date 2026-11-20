import { existsSync, mkdirSync, readdirSync, realpathSync } from 'fs'
import path from 'path'
import { parseArgs } from 'util'

import { seedBacklog } from './backlog/backlog'
import { Backlog, CardError, LoadedCard, Profile, Target, load, readProfile } from './cards'
import { DevConfig, devConfigOf } from './dev-target/config'
import { devEnvironment, devTarget } from './dev-target/target'
import { createEnvironment, defaultStateDir } from './environment/environment'
import { StackConflictError, holdRunLock } from './environment/processes'
import { roleSpecs, secretsOf } from './environment/roles'
import { cyclotronUrlOf } from './environment/stack'
import { Runner, createRunner } from './runner/runner'
import { readSavedRun, savedRunPathOf } from './runner/saved-run'
import { EXIT_CODE, exitCodeOf } from './runner/status'
import { ADAPTERS } from './scorecard/scorecard'
import { credentialsOf } from './scorecard/write'
import { STORE_URL, reportToStore, storeTokenPathOf } from './store/client'
import { RunId } from './store/runs'

const CARDS_DIR = path.join(__dirname, 'cards')
const USAGE = [
    'Usage: pnpm --dir nodejs exec tsx tests/scenarios/main.ts run <card id or path>... [--profile <file>] [--target local|dev]',
    '       pnpm --dir nodejs exec tsx tests/scenarios/main.ts seed-backlog --profile <file>',
    '       pnpm --dir nodejs exec tsx tests/scenarios/main.ts publish <run id or run directory>... | --all',
].join('\n')

function cardPathOf(card: string, target: Target): string {
    const dir = target === 'dev' ? path.join(CARDS_DIR, 'dev') : CARDS_DIR
    return card.endsWith('.yaml') || card.includes('/') ? path.resolve(card) : path.join(dir, `${card}.yaml`)
}

function preflight(
    cards: string[],
    profilePath: string | undefined,
    target: Target,
    env: NodeJS.ProcessEnv
): { loaded: LoadedCard[]; dev?: DevConfig } | { problems: string[] } {
    const { problem } = credentialsOf(env)
    const problems = problem === undefined ? [] : [problem]
    let dev: DevConfig | undefined
    try {
        dev = target === 'dev' ? devConfigOf(env) : undefined
    } catch (error) {
        problems.push((error as Error).message)
    }
    const loaded = cards.flatMap((card) => {
        try {
            return [load(cardPathOf(card, target), { profilePath, target })]
        } catch (error) {
            problems.push(error instanceof CardError ? error.message : `${card}: ${(error as Error).message}`)
            return []
        }
    })
    return problems.length > 0 ? { problems } : { loaded, dev }
}

export async function main(argv: string[], env: NodeJS.ProcessEnv = process.env): Promise<number> {
    const { positionals, values } = parseArgs({
        args: argv,
        allowPositionals: true,
        options: {
            profile: { type: 'string' },
            all: { type: 'boolean' },
            target: { type: 'string', default: 'local' },
        },
    })
    const [command, ...cards] = positionals
    if (command === 'seed-backlog' && cards.length === 0 && values.profile !== undefined) {
        return seedBacklogOf(values.profile, env)
    }
    const publishesAll = values.all === true
    const namesRuns = cards.length > 0
    if (command === 'publish' && publishesAll !== namesRuns) {
        return publishRuns(cards, env)
    }
    const target = values.target
    if (command !== 'run' || cards.length === 0 || (target !== 'local' && target !== 'dev')) {
        process.stderr.write(`${USAGE}\n`)
        return EXIT_CODE.invalid
    }
    const checked = preflight(cards, values.profile, target, env)
    if ('problems' in checked) {
        process.stderr.write(`${checked.problems.join('\n\n')}\n`)
        return EXIT_CODE.invalid
    }

    const interrupt = new AbortController()
    process.once('SIGINT', () => interrupt.abort())
    process.once('SIGTERM', () => interrupt.abort())
    const { dev } = checked
    const runner = dev
        ? createRunner(devEnvironment(), env, { target: devTarget(dev) })
        : createRunner(createEnvironment(), env)
    return runCards(runner, checked.loaded, interrupt.signal)
}

function runDirsOf(runs: string[], env: NodeJS.ProcessEnv): string[] {
    const stateDir = defaultStateDir(env)
    if (runs.length > 0) {
        return runs.map((run) => {
            const local = path.resolve(run)
            return existsSync(local) || !RunId.safeParse(run).success ? local : path.join(stateDir, run)
        })
    }
    if (!existsSync(stateDir)) {
        return []
    }
    return readdirSync(stateDir)
        .filter((name) => RunId.safeParse(name).success && existsSync(savedRunPathOf(path.join(stateDir, name))))
        .sort()
        .map((name) => path.join(stateDir, name))
}

async function publishSaved(runDir: string, env: NodeJS.ProcessEnv): Promise<string | undefined> {
    const saved = readSavedRun(runDir)
    if ('problem' in saved) {
        return saved.problem
    }
    const { event, host } = saved.run
    const scorecard = { ...event, adapters: event.adapters ?? ADAPTERS }
    return (await reportToStore({ scorecard, host }, env)).problem
}

async function publishRuns(runs: string[], env: NodeJS.ProcessEnv): Promise<number> {
    if (!env[STORE_URL]) {
        process.stderr.write(
            `Set ${STORE_URL} to the run store's URL, and put its run token in ${storeTokenPathOf(env)}.\n`
        )
        return EXIT_CODE.invalid
    }
    let code: number = EXIT_CODE.passed
    for (const runDir of runDirsOf(runs, env)) {
        const problem = await publishSaved(runDir, env).catch((error: Error) => error.message)
        if (problem === undefined) {
            process.stdout.write(`${path.basename(runDir)}: stored\n`)
        } else {
            process.stderr.write(`${path.basename(runDir)}: ${problem}\n`)
            code = EXIT_CODE.writeFailed
        }
    }
    return code
}

async function seedBacklogOf(profilePath: string, env: NodeJS.ProcessEnv): Promise<number> {
    const read = readProfile(profilePath)
    if ('problems' in read) {
        process.stderr.write(`${new CardError(profilePath, read.problems).message}\n`)
        return EXIT_CODE.invalid
    }
    const { name, backlog, settings } = read.profile
    if (backlog === undefined) {
        process.stderr.write(`${profilePath} has no backlog to seed\n`)
        return EXIT_CODE.invalid
    }
    const stateDir = defaultStateDir(env)
    mkdirSync(stateDir, { recursive: true })
    const release = await holdRunLock(realpathSync(stateDir)).catch((error: unknown) => {
        if (error instanceof StackConflictError) {
            process.stderr.write(`${error.message}\n`)
            return undefined
        }
        throw error
    })
    if (release === undefined) {
        return EXIT_CODE.invalid
    }
    try {
        return await seedHeld(name, backlog, settings, stateDir, env)
    } finally {
        await release()
    }
}

async function seedHeld(
    name: string,
    backlog: Backlog,
    settings: Profile['settings'],
    stateDir: string,
    env: NodeJS.ProcessEnv
): Promise<number> {
    const [spec] = roleSpecs(env, { url: '' }, secretsOf(env), stateDir, settings)
    const { queues, bytes, manifest } = await seedBacklog(name, backlog, cyclotronUrlOf(spec), stateDir)
    for (const { queue, target, live } of queues) {
        process.stdout.write(`${queue}: ${live} live rows of ${target}\n`)
    }
    process.stdout.write(
        `cyclotron_jobs bytes, every row and dead tuple included: table ${bytes.table}, indexes ${bytes.indexes}, toast ${bytes.toast}\n`
    )
    const outside = queues.filter(({ withinTolerance }) => !withinTolerance)
    for (const { queue, target, live } of outside) {
        const share = Number((backlog.tolerance * 100).toFixed(2))
        process.stderr.write(`${queue}: ${live} live rows, outside ${share}% of the ${target} the profile asks for\n`)
    }
    if (manifest === undefined) {
        return EXIT_CODE.invalid
    }
    process.stdout.write(`manifest: ${manifest}\n`)
    return EXIT_CODE.passed
}

export async function runCards(runner: Runner, cards: LoadedCard[], interrupt: AbortSignal): Promise<number> {
    let code: number = EXIT_CODE.passed
    let ran = 0
    try {
        await runner.up(interrupt)
        for (const loaded of cards) {
            if (interrupt.aborted) {
                break
            }
            const result = await runner.run(loaded, interrupt)
            process.stdout.write(`${result.cardId}: ${result.status}, ${result.statusReason}\n`)
            process.stdout.write(`evidence: ${result.evidenceDir}\n`)
            const readBackSkipped = result.captured ? ['captured; the run was interrupted before it was read back'] : []
            const recording = result.recorded ? ['recorded'] : readBackSkipped
            const problems = result.scorecardError ? [result.scorecardError] : []
            const scorecard = [...recording, ...problems].join('; ') || 'not written, no credentials set'
            process.stdout.write(`scorecard: ${scorecard}\n`)
            const store = result.stored ? 'stored' : (result.storeError ?? `not reported, ${STORE_URL} is not set`)
            process.stdout.write(`store: ${store}\n`)
            code = Math.max(code, exitCodeOf(result))
            ran += 1
        }
    } catch (error) {
        process.stderr.write(`${(error as Error).message}\n`)
        code = Math.max(code, (error as { exitCode?: number }).exitCode ?? EXIT_CODE.invalid)
    } finally {
        await runner.down()
    }
    if (ran < cards.length) {
        const skipped = `${cards.length - ran} of ${cards.length} cards`
        process.stderr.write(
            interrupt.aborted ? `Interrupted before ${skipped} ran.\n` : `Skipped ${skipped} after the error.\n`
        )
        code = Math.max(code, EXIT_CODE.invalid)
    }
    return code
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
