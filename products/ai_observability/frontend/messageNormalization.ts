import posthog from 'posthog-js'

import {
    mergeRecipes,
    RecipeNormalizer,
    RunOutcome,
    setNormalizerTelemetry,
    StoredRecipe,
} from '@posthog/llm-normalizer'

import { CompatMessage } from './types'

export type NormalizationResult = RunOutcome

// Route the portable normalizer's telemetry back through posthog-js in the browser.
// Headless callers (MCP server, tasks sandbox) leave the noop default in place.
setNormalizerTelemetry((event, properties) => posthog.capture(event, properties))

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
    return recipeNormalizer.normalizeMessage(input, defaultRole).messages
}

export function normalizeMessages(input: unknown, defaultRole: string, tools?: unknown): NormalizationResult {
    return recipeNormalizer.normalizeMessages(input, defaultRole, tools)
}

export function captureNormalizationFailure(input: unknown): void {
    posthog.capture('llma message normalization failed', {
        message_keys: typeof input === 'object' && input !== null ? Object.keys(input) : [],
        message_type: typeof input,
    })
}
