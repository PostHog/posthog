import path from 'path'
import { parseArgs } from 'util'

import { CardError, LoadedCard, load } from './cards'
import { createEnvironment } from './environment/environment'
import { Runner, createRunner } from './runner/runner'
import { EXIT_CODE } from './runner/status'

const CARDS_DIR = path.join(__dirname, 'cards')
const USAGE = 'Usage: pnpm --dir nodejs exec tsx tests/scenarios/main.ts run <card id or path>... [--profile <file>]'

function cardPathOf(card: string): string {
    return card.endsWith('.yaml') || card.includes('/') ? path.resolve(card) : path.join(CARDS_DIR, `${card}.yaml`)
}

function preflight(
    cards: string[],
    profilePath: string | undefined
): { loaded: LoadedCard[] } | { problems: string[] } {
    const problems: string[] = []
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

async function main(argv: string[]): Promise<number> {
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
    const checked = preflight(cards, values.profile)
    if ('problems' in checked) {
        process.stderr.write(`${checked.problems.join('\n\n')}\n`)
        return EXIT_CODE.invalid
    }

    const interrupt = new AbortController()
    process.once('SIGINT', () => interrupt.abort())
    process.once('SIGTERM', () => interrupt.abort())
    return runCards(createRunner(createEnvironment()), checked.loaded, interrupt.signal)
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
            code = Math.max(code, EXIT_CODE[result.status])
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
