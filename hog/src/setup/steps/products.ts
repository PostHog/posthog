import { escapeControls } from '@/core/output'

import type { SkillInfo } from '../result'
import type { SetupRun, Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

const ADD_SKILLS = 'hog skills add <id...>'

const INSTRUCTIONS = [
    'Tell the person what else PostHog can do, from context.products.',
    `Name the skills in context.skills that could help them later, and say they can add them with \`${ADD_SKILLS}\`.`,
    `Then run \`${SETUP_NEXT} --products-ack\` yourself.`,
].join(' ')

// A list that fails to load only leaves the skills out of this step.
async function skillList(run: SetupRun): Promise<SkillInfo[]> {
    let failure: string
    try {
        const result = await (await run.ctx.skills()).installable()
        if (result.ok) {
            return result.value.skills.map(({ id, name, description }) => ({ id, name, description }))
        }

        failure = result.error.message
    } catch (error) {
        failure = error instanceof Error ? error.message : String(error)
    }

    run.context.warnings.push(`The PostHog skills didn't load: ${failure}`)
    return []
}

export const products: Step = {
    summary: () => 'Went through what else PostHog can do',

    async advance(run) {
        const { ctx, input } = run
        // Both load the same skills release, so they share one download.
        const [products, skills] = await Promise.all([run.productsContext(), skillList(run)])
        run.context.products = products
        run.context.skills = skills

        const prompts = input.next ? ctx.prompts : undefined
        if (!input.productsAck && prompts) {
            const lines = products.map((product) => `${product.label}: ${product.command}`)
            const skillLines = skills.map((skill) => `${skill.id}: ${skill.description}`)
            prompts.note(escapeControls(lines.join('\n')), 'What else PostHog can do')
            if (skillLines.length > 0) {
                prompts.note(escapeControls(skillLines.join('\n')), `Skills you can add with ${ADD_SKILLS}`)
            }
        }

        if (input.productsAck || prompts) {
            await run.complete('products')
            return undefined
        }

        return {
            code: 'setup_products_pending',
            next: { kind: 'tell_user', command: `${SETUP_NEXT} --products-ack`, instructions: INSTRUCTIONS },
        }
    },
}
