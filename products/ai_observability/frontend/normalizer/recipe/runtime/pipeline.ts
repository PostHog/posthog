import posthog from 'posthog-js'

import { DispatchEngine, DispatchResult, NO_MATCH, Rule } from '../ast/rule'
import { Scope } from '../scope'
import { Recipe } from '../spec/recipe'
import { SlotCoercer } from './coercion'

export { NO_MATCH } from '../ast/rule'
export type { DispatchResult } from '../ast/rule'

// Insurance against a recipe that delegates to a shape matching itself.
const MAX_DEPTH = 10

export class RecipePipeline implements DispatchEngine {
    readonly coercer = new SlotCoercer()
    private readonly recipes: Recipe[]

    constructor(recipes: Recipe[]) {
        // Sort a copy: the input is the shared module-level registry array.
        this.recipes = [...recipes].sort((a, b) => a.priority - b.priority)
    }

    run(input: unknown, defaultRole: string): DispatchResult {
        return this.dispatch(input, defaultRole, 0)
    }

    dispatch(input: unknown, inheritedRole: string, depth: number): DispatchResult {
        if (depth > MAX_DEPTH) {
            throw new Error(
                `RecipeNormalizer: delegation exceeded max depth (${MAX_DEPTH}) — a recipe likely delegates to itself`
            )
        }
        for (const recipe of this.recipes) {
            for (const rule of recipe.rules) {
                const result = this.applyRule(rule, input, inheritedRole, depth)
                if (result !== NO_MATCH) {
                    if (recipe.capture) {
                        posthog.capture(recipe.capture, {
                            message_keys: typeof input === 'object' && input !== null ? Object.keys(input) : [],
                            message_type: typeof input,
                        })
                    }
                    return result
                }
            }
        }
        return NO_MATCH
    }

    private applyRule(rule: Rule, input: unknown, inheritedRole: string, depth: number): DispatchResult {
        if (!rule.on.matches(input)) {
            return NO_MATCH
        }
        const scope = Scope.forNode(input, inheritedRole)

        // Past the match, the rule owns this input and never returns NO_MATCH.
        // Followups are built first so `produce` can drop an empty primary only
        // when followups exist (the OTel "responses-only" case).
        const followups = rule.buildFollowups(scope, this)
        const primary = rule.produce(scope, this, followups.length > 0, depth)
        return [...primary, ...followups]
    }
}
