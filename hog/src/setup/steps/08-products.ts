import type { SkillInfo } from '../result'
import { runNext, type SetupRun, type Step } from '../setup-run'
import { SETUP_NEXT } from '../state'

export const ADD_SKILLS = 'hog skills add <skill...>'

// Setup has just added PostHog to the code, so the skills worth keeping for later are the ones for
// using it. A list that fails to load only leaves the skills out of this step.
async function skillList(run: SetupRun): Promise<SkillInfo[]> {
    let failure: string
    try {
        const result = await (await run.ctx.skills()).catalog()
        if (result.ok) {
            return result.value.skills
                .filter((skill) => skill.kind === 'learning')
                .map(({ name, description }) => ({ id: name, name, description }))
        }

        failure = result.error.message
    } catch (error) {
        failure = error instanceof Error ? error.message : String(error)
    }

    run.context.warnings.push(`Couldn't load the PostHog skills: ${failure}`)
    return []
}

export const products: Step = {
    summary: () => 'Listed what else PostHog can do',

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
