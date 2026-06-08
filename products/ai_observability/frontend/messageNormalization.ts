import { mergeRecipes, RecipeNormalizer, StoredRecipe } from './normalizer'
import { CompatMessage } from './types'

// Constructed once: the constructor compiles and sorts every recipe, so per-call
// construction would be wasteful.
const recipeNormalizer = new RecipeNormalizer()

// Swap the live normalizer over to a team's custom recipe set. Called wherever traces
// render once the team's recipes load (and after every edit). Wrapped so a malformed
// config can never break trace rendering — we keep the prior set on error.
export function applyTeamParserRecipes(stored: StoredRecipe[]): void {
    try {
        recipeNormalizer.setRecipes(mergeRecipes(stored))
    } catch {
        // keep whatever set is currently active
    }
}

export function normalizeMessage(input: unknown, defaultRole: string): CompatMessage[] {
    return recipeNormalizer.normalizeMessage(input, defaultRole)
}

export function normalizeMessages(input: unknown, defaultRole: string, tools?: unknown): CompatMessage[] {
    return recipeNormalizer.normalizeMessages(input, defaultRole, tools)
}
