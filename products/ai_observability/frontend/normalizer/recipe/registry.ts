import { parse as parseYaml } from 'yaml'

import { compileRecipe } from './compile/compiler'
import anthropic from './default_recipes/anthropic.yaml?raw'
import compatArray from './default_recipes/compat_array.yaml?raw'
import dispatcherEntry from './default_recipes/dispatcher_entry.yaml?raw'
import langchain from './default_recipes/langchain.yaml?raw'
import langchainEnvelope from './default_recipes/langchain_envelope.yaml?raw'
import litellm from './default_recipes/litellm.yaml?raw'
import openaiChat from './default_recipes/openai_chat.yaml?raw'
import openaiResponses from './default_recipes/openai_responses.yaml?raw'
import otel from './default_recipes/otel.yaml?raw'
import typedAgentItems from './default_recipes/typed_agent_items.yaml?raw'
import vercelSdk from './default_recipes/vercel_sdk.yaml?raw'
import wrappers from './default_recipes/wrappers.yaml?raw'
import { Recipe } from './spec/recipe'

// Order here determines deafult recipe order
const RECIPE_SOURCES: readonly string[] = [
    dispatcherEntry,
    compatArray,
    litellm,
    langchainEnvelope,
    langchain,
    vercelSdk,
    openaiChat,
    openaiResponses,
    typedAgentItems,
    anthropic,
    otel,
    wrappers,
]

const RECIPES: Recipe[] = []
const seenIds = new Set<string>()
for (const [index, source] of RECIPE_SOURCES.entries()) {
    let recipe: Recipe
    try {
        recipe = compileRecipe(parseYaml(source))
    } catch (err) {
        throw new Error(`Loading recipe #${index}: ${err instanceof Error ? err.message : String(err)}`)
    }
    if (seenIds.has(recipe.id)) {
        throw new Error(`Duplicate recipe id '${recipe.id}'`)
    }
    seenIds.add(recipe.id)
    RECIPES.push(recipe)
}

export function loadRecipes(): Recipe[] {
    return RECIPES
}
