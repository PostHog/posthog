import { parse as parseYaml } from 'yaml'

import { compileRecipe } from './compile/compiler'
import { loadRecipes } from './registry'
import { Recipe } from './spec/recipe'

// A team's net-new custom recipe. Mirrors the `ParserRecipe` API row, narrowed to
// what the merge needs so the normalizer stays decoupled from generated API types.
export interface StoredRecipe {
    id: string
    source: string
}

// `cajole` is the builtin last-resort catch-all; customs dispatch just before it so
// they get a shot at inputs the specific builtins miss, while never shadowing them.
const CATCH_ALL_RECIPE_ID = 'cajole'

// Resolve a team's custom recipes into the ordered set the pipeline runs: the bundled
// builtins in their dispatch order, with the team's customs spliced in (in their stored
// order) right before the catch-all. A custom that fails to compile is skipped — there's
// no builtin to fall back to — so a bad edit can never break trace rendering.
export function mergeRecipes(stored: StoredRecipe[]): Recipe[] {
    const builtins = loadRecipes()
    const customs = stored.map(tryCompile).filter((recipe): recipe is Recipe => recipe !== undefined)

    const catchAllIndex = builtins.findIndex((recipe) => recipe.id === CATCH_ALL_RECIPE_ID)
    const insertAt = catchAllIndex === -1 ? builtins.length : catchAllIndex
    return [...builtins.slice(0, insertAt), ...customs, ...builtins.slice(insertAt)]
}

function tryCompile(recipe: StoredRecipe): Recipe | undefined {
    try {
        // The database id is the recipe's identity, regardless of any `id:` in the source.
        return { ...compileRecipe(parseYaml(recipe.source), recipe.id), id: recipe.id }
    } catch {
        return undefined
    }
}
