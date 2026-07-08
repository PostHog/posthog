// The recipe-based message normalizer. Production routes through
// `../messageNormalization`; this module is also exercised directly by tests.

export { RecipeNormalizer } from './recipe/recipeNormalizer'
export type { RunOutcome } from './recipe/runtime/pipeline'
export { mergeRecipes } from './recipe/merge'
export type { StoredRecipe } from './recipe/merge'
export { compileRecipe } from './recipe/compile/compiler'
