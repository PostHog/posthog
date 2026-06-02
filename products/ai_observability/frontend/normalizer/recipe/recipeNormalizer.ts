import { CompatMessage } from '../../types'
import { AVAILABLE_TOOLS_ROLE, safeStringify } from '../../utils'
import { loadRecipes } from './registry'
import { NO_MATCH, RecipePipeline } from './runtime/pipeline'

export class RecipeNormalizer {
    private readonly pipeline: RecipePipeline

    constructor() {
        this.pipeline = new RecipePipeline(loadRecipes())
    }

    normalizeMessage(input: unknown, defaultRole: string): CompatMessage[] {
        // `undefined` carries no message (a missing field, a sparse array slot). cajole
        // intentionally doesn't match it, so handle it here rather than dispatch a miss.
        if (input === undefined) {
            return []
        }
        const result = this.pipeline.run(input, defaultRole)
        if (result === NO_MATCH) {
            // cajole.yaml matches anything, so NO_MATCH means a coverage gap, not a normal miss.
            throw new Error(
                `RecipeNormalizer: no recipe matched ${safeStringify(input, 0).slice(0, 200)} — cajole.yaml should be the final catch-all`
            )
        }
        return result
    }

    normalizeMessages(input: unknown, defaultRole: string, tools?: unknown): CompatMessage[] {
        const messages: CompatMessage[] = []
        if (tools) {
            // `tools` is a function parameter, not a message shape, so it has no recipe.
            messages.push({ role: AVAILABLE_TOOLS_ROLE, content: '', tools })
        }
        messages.push(...this.normalizeMessage(input, defaultRole))
        return messages
    }
}
