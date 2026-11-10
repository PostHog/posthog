import { EXIT_USAGE, HogError } from '@/core/errors'
import { REGION_CHOICES, REGIONS, regionOf, type RegionId } from '@/posthog/host'

import { PRODUCT_IDS, productLabel, type ProductId } from '../products'
import type { SetupInput } from '../result'
import type { SetupRun, Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

const QUESTION = 'What do you want to use PostHog for?'
const COMMAND = `${SETUP_NEXT} --reason "<their answer>" --products <id,id>`

const SENT_NOTICE = 'hog sends your answer to PostHog to improve setup.'
const KEPT_NOTICE = 'Your answer stays on this machine.'

// The agent asks in our place, so it passes on the same notice the terminal shows.
function instructions(telemetry: boolean): string {
    const notice = telemetry
        ? `Tell them: "${SENT_NOTICE} To keep it on this machine, set \`HOG_NO_TELEMETRY=1\`."`
        : `Tell them: "${KEPT_NOTICE}"`

    return [
        `Ask the user: "${QUESTION}"`,
        notice,
        `Pick the products in \`context.products\` that match the answer, then run \`${COMMAND}\`.`,
        'If none match, pass `--products product-analytics`.',
        'Add `--region eu` only if the user mentions the EU or data residency.',
    ].join(' ')
}

type Answers = Pick<SetupInput, 'reason' | 'products' | 'region'>

// A person at the terminal answers what the options left out. The region is asked only when nothing
// names a host.
async function askAtTerminal(run: SetupRun, given: Answers, needsRegion: boolean): Promise<Answers> {
    const prompts = run.input.next ? run.ctx.prompts : undefined
    if (!prompts) {
        return given
    }

    const help = run.ctx.telemetry.isEnabled ? SENT_NOTICE : KEPT_NOTICE
    const reason =
        given.reason ??
        (await prompts.text(QUESTION, {
            help,
            validate: (value) => (value.trim() ? undefined : 'Write a few words about it.'),
        }))

    const products = await run.products()
    const picked =
        given.products ??
        (await prompts.multiselect<ProductId>(
            'Which PostHog products do you want to start with?',
            products.map(({ id, label, description }) => ({ value: id, label, hint: description })),
            { help: 'Press Space to select a product and Enter to continue.' }
        ))

    const region =
        given.region ??
        (needsRegion
            ? await prompts.select<RegionId>('Where should your PostHog data be hosted?', REGION_CHOICES, {
                  help: "If you already have an account, pick where it's hosted. EU Cloud keeps your data in the EU.",
              })
            : undefined)

    return { reason, products: picked, region }
}

export const purpose: Step = {
    isDone: async (run) => run.state !== undefined,

    summary: (run) => {
        const picked = (run.state?.products ?? []).map(productLabel)
        return picked.length > 0 ? `Picked ${picked.join(', ')}` : 'Said what PostHog is for'
    },

    async advance(run) {
        const { ctx, input } = run
        const named = await run.namedHost()
        const given = { reason: input.reason, products: input.products, region: input.region }
        const { reason, products, region } = await askAtTerminal(run, given, named === undefined)

        if (reason === undefined || products === undefined) {
            if (Object.values(given).some((answer) => answer !== undefined)) {
                const missing = reason === undefined ? '--reason' : '--products'
                throw new HogError(
                    'setup_needs_answers',
                    `Pass ${missing} too.`,
                    `Run \`${COMMAND}\` with both. Product IDs: ${PRODUCT_IDS.join(', ')}.`,
                    EXIT_USAGE
                )
            }

            run.context.products = await run.productsContext()
            return {
                code: 'setup_needs_answers',
                next: {
                    kind: 'ask_user',
                    ask: QUESTION,
                    command: COMMAND,
                    instructions: instructions(ctx.telemetry.isEnabled),
                },
            }
        }

        const host = named ?? REGIONS[region ?? 'us']
        run.state = {
            folder: run.scope.folder,
            startedAt: ctx.runtime.now(),
            reason,
            products,
            host,
            reads: [],
            completed: [],
        }

        // The reason is the one text a person typed that telemetry carries, because the question says so.
        ctx.telemetry.capture('hog setup started', { reason, products, region: regionOf(host) ?? null })
        await run.complete('purpose')

        return undefined
    },
}
