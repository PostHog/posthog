import { parse as parseYaml } from 'yaml'

import { compileRecipe } from './compile/compiler'
import anthropic from './default_recipes/anthropic.yaml?raw'
import cajole from './default_recipes/cajole.yaml?raw'
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

const RECIPE_SOURCES = {
    anthropic,
    cajole,
    compatArray,
    dispatcherEntry,
    langchain,
    langchainEnvelope,
    litellm,
    openaiChat,
    openaiResponses,
    otel,
    typedAgentItems,
    vercelSdk,
    wrappers,
}

const RECIPES: Recipe[] = Object.entries(RECIPE_SOURCES).map(([name, source]) => {
    try {
        return compileRecipe(parseYaml(source))
    } catch (err) {
        throw new Error(`Loading recipe ${name}: ${err instanceof Error ? err.message : String(err)}`)
    }
})

// Dispatch is first-match-wins over priority order, so two recipes sharing a
// priority would have an undefined relative order. Fail loudly instead.
const seenPriorities = new Map<number, string>()
for (const recipe of RECIPES) {
    const clash = seenPriorities.get(recipe.priority)
    if (clash !== undefined) {
        throw new Error(`Recipe priority ${recipe.priority} is used by both '${clash}' and '${recipe.id}'`)
    }
    seenPriorities.set(recipe.priority, recipe.id)
}

export function loadRecipes(): Recipe[] {
    return RECIPES
}
