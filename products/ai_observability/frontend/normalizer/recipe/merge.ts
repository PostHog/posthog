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

// Resolve a team's custom recipes into the ordered set the pipeline runs: the bundled
// builtins in their dispatch order, followed by the team's customs (in their stored
// order). Customs run last among the matchers — after every builtin but before the
// pipeline's catch-all salvage — so they catch inputs the builtins miss without ever
// shadowing them. A custom that fails to compile is skipped, so a bad edit can never
// break trace rendering.
export function mergeRecipes(stored: StoredRecipe[]): Recipe[] {
    const customs = stored.map(tryCompile).filter((recipe): recipe is Recipe => recipe !== undefined)
    return [...loadRecipes(), ...customs]
}

function tryCompile(recipe: StoredRecipe): Recipe | undefined {
    try {
        // The database id is the recipe's identity, regardless of any `id:` in the source.
        return { ...compileRecipe(parseYaml(recipe.source), recipe.id), id: recipe.id }
    } catch {
        return undefined
    }
}
