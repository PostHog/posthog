// Recipe-based parallel to the legacy `../utils` normalizer. Production routes
// through `../messageNormalization`, which flag-switches between the two; this
// module is also exercised directly by the parity test suite.

export { RecipeNormalizer } from './recipe/recipeNormalizer'
export { mergeRecipes } from './recipe/merge'
export type { StoredRecipe } from './recipe/merge'
export { compileRecipe } from './recipe/compile/compiler'
