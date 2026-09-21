// Portable LLM analytics message normalizer + recipe DSL. Shared by the PostHog frontend
// (products/ai_observability) and headless runtimes (services/mcp) — keep it free of
// browser- and app-coupled imports.

export { RecipeNormalizer } from './normalizer/recipe/recipeNormalizer'
export type { RunOutcome } from './normalizer/recipe/runtime/pipeline'
export { mergeRecipes } from './normalizer/recipe/merge'
export type { StoredRecipe } from './normalizer/recipe/merge'
export { compileRecipe } from './normalizer/recipe/compile/compiler'
export { setNormalizerTelemetry } from './normalizer/telemetry'
export { roleMap, normalizeRole, AVAILABLE_TOOLS_ROLE } from './normalizer/roles'
export { validateRecipeAgainstSample, handleCreateParserRecipeCall } from './validateRecipe'
export type { RecipeValidationSample, RecipeVerdict, CreateParserRecipeHandlerDeps } from './validateRecipe'
export { sampleForContext } from './sampleForContext'
