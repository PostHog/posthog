import type { SkillInfo } from '../result'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

export const ADD_SKILLS = 'hog skills add <id...>'

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
        if (!run.input.next) {
            return runNext('setup_products_pending', `Run \`${SETUP_NEXT}\` to finish setup.`)
        }

        // Both load the same skills release, so they share one download.
        const [products, skills] = await Promise.all([run.productsContext(), skillList(run)])
        run.context.products = products
        run.context.skills = skills

        await run.complete('products')
        return undefined
    },
}
