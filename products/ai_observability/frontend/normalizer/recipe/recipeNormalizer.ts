import { CompatMessage } from '../../types'
import { AVAILABLE_TOOLS_ROLE } from '../../utils'
import { loadRecipes } from './registry'
import { RecipePipeline, RunOutcome } from './runtime/pipeline'
import { Recipe } from './spec/recipe'

export class RecipeNormalizer {
    private pipeline: RecipePipeline

    constructor(recipes: Recipe[] = loadRecipes()) {
        this.pipeline = new RecipePipeline(recipes)
    }

    setRecipes(recipes: Recipe[]): void {
        this.pipeline = new RecipePipeline(recipes)
    }

    normalizeMessage(input: unknown, defaultRole: string): RunOutcome {
        // `undefined` carries no message (a missing field, a sparse array slot) and
        // nothing to recognize — treat as an empty, recognized result.
        if (input === undefined) {
            return { messages: [], recognized: true }
        }
        return this.pipeline.run(input, defaultRole)
    }

    normalizeMessages(input: unknown, defaultRole: string, tools?: unknown): RunOutcome {
        const messages: CompatMessage[] = []
        if (tools) {
            // `tools` is a function parameter, not a message shape, so it has no recipe.
            messages.push({ role: AVAILABLE_TOOLS_ROLE, content: '', tools })
        }
        if (carriesMessages(input)) {
            const outcome = this.normalizeMessage(input, defaultRole)
            messages.push(...outcome.messages)
            return { messages, recognized: outcome.recognized }
        }
        return { messages, recognized: true }
    }
}

function carriesMessages(input: unknown): boolean {
    return Array.isArray(input) || typeof input === 'string' || (typeof input === 'object' && input !== null)
}
