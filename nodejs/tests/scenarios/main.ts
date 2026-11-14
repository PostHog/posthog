import path from 'path'
import { parseArgs } from 'util'

import { CardError, LoadedCard, load } from './cards'
import { createEnvironment } from './environment/environment'
import { Runner, createRunner } from './runner/runner'
import { EXIT_CODE, exitCodeOf } from './runner/status'
import { credentialsOf } from './scorecard/write'

const CARDS_DIR = path.join(__dirname, 'cards')
const USAGE = 'Usage: pnpm --dir nodejs exec tsx tests/scenarios/main.ts run <card id or path>... [--profile <file>]'

function cardPathOf(card: string): string {
    return card.endsWith('.yaml') || card.includes('/') ? path.resolve(card) : path.join(CARDS_DIR, `${card}.yaml`)
}

function preflight(
    cards: string[],
    profilePath: string | undefined,
    env: NodeJS.ProcessEnv
): { loaded: LoadedCard[] } | { problems: string[] } {
    const { problem } = credentialsOf(env)
    const problems = problem === undefined ? [] : [problem]
    const loaded = cards.flatMap((card) => {
        try {
            return [load(cardPathOf(card), { profilePath })]
        } catch (error) {
            problems.push(error instanceof CardError ? error.message : `${card}: ${(error as Error).message}`)
            return []
        }
    })
    return problems.length > 0 ? { problems } : { loaded }
}

export async function main(argv: string[], env: NodeJS.ProcessEnv = process.env): Promise<number> {
    const { positionals, values } = parseArgs({
        args: argv,
        allowPositionals: true,
        options: { profile: { type: 'string' } },
    })
    const [command, ...cards] = positionals
    if (command !== 'run' || cards.length === 0) {
        process.stderr.write(`${USAGE}\n`)
        return EXIT_CODE.invalid
    }
    const checked = preflight(cards, values.profile, env)
    if ('problems' in checked) {
        process.stderr.write(`${checked.problems.join('\n\n')}\n`)
        return EXIT_CODE.invalid
    }

    const interrupt = new AbortController()
    process.once('SIGINT', () => interrupt.abort())
    process.once('SIGTERM', () => interrupt.abort())
    return runCards(createRunner(createEnvironment(), env), checked.loaded, interrupt.signal)
}

export async function runCards(runner: Runner, cards: LoadedCard[], interrupt: AbortSignal): Promise<number> {
    let code: number = EXIT_CODE.passed
    let ran = 0
    try {
        await runner.up()
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
