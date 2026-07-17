import { CompatMessage } from '../../../types'
import { DispatchEngine, DispatchResult, NO_MATCH, Rule } from '../ast/rule'
import { Scope } from '../scope'
import { Recipe } from '../spec/recipe'
import { SlotCoercer } from './coercion'

export { NO_MATCH } from '../ast/rule'
export type { DispatchResult } from '../ast/rule'

export interface RunOutcome {
    messages: CompatMessage[]
    recognized: boolean
}

// Insurance against a recipe that delegates to a shape matching itself.
const MAX_DEPTH = 10

export class RecipePipeline implements DispatchEngine {
    readonly coercer = new SlotCoercer()
    private readonly recipes: Recipe[]

    constructor(recipes: Iterable<Recipe>) {
        this.recipes = [...recipes]
    }

    run(input: unknown, defaultRole: string): RunOutcome {
        const matched = this.matchRecipes(input, defaultRole, 0)
        if (matched !== NO_MATCH) {
            return { messages: matched, recognized: true }
        }
        const salvaged = this.salvage(input, defaultRole)
        return { messages: salvaged === NO_MATCH ? [] : salvaged, recognized: false }
    }

    // Delegation (delegate/delegateEach) salvages unmatched children so nested
    // fragments survive instead of being dropped.
    dispatch(input: unknown, inheritedRole: string, depth: number): DispatchResult {
        const matched = this.matchRecipes(input, inheritedRole, depth)
        return matched !== NO_MATCH ? matched : this.salvage(input, inheritedRole)
    }

    private matchRecipes(input: unknown, inheritedRole: string, depth: number): DispatchResult {
        if (depth > MAX_DEPTH) {
            throw new Error(
                `RecipeNormalizer: delegation exceeded max depth (${MAX_DEPTH}) — a recipe likely delegates to itself`
            )
        }
        for (const recipe of this.recipes) {
            for (const rule of recipe.rules) {
                const result = this.applyRule(rule, input, inheritedRole, depth)
                if (result !== NO_MATCH) {
                    return result
                }
            }
        }
        return NO_MATCH
    }

    private salvage(input: unknown, inheritedRole: string): DispatchResult {
        if (input === undefined) {
            return NO_MATCH
        }
        const role = Scope.forNode(input, inheritedRole).role
        const content =
            isPlainObject(input) && typeof input.content === 'string' ? input.content : stringifyContent(input)
        return [{ role, content }]
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

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringifyContent(value: unknown): string {
    if (value === null) {
        return ''
    }
    if (typeof value === 'string') {
        return value
    }
    try {
        return JSON.stringify(value) ?? ''
    } catch {
        return String(value)
    }
}
