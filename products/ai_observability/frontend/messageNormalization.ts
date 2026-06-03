import posthog, { JsonType } from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { objectsEqual, removeUndefinedAndNull } from 'lib/utils'

import { RecipeNormalizer } from './normalizer'
import { CompatMessage } from './types'
import { normalizeMessage as legacyNormalizeMessage, normalizeMessages as legacyNormalizeMessages } from './utils'

// Constructed once: the constructor compiles and sorts every recipe, so per-call
// construction would dwarf the work we're measuring.
const recipeNormalizer = new RecipeNormalizer()

// Normalization runs once per rendered message; sample so timing doesn't flood ingestion.
const DEFAULT_TIMING_SAMPLE_RATE = 0.01

function timingSampleRate(payload: JsonType | undefined): number {
    if (payload && typeof payload === 'object' && 'sample_rate' in payload) {
        const rate = Number(payload.sample_rate)
        if (Number.isFinite(rate) && rate >= 0 && rate <= 1) {
            return rate
        }
    }
    return DEFAULT_TIMING_SAMPLE_RATE
}

export function normalizeMessage(input: unknown, defaultRole: string): CompatMessage[] {
    return dispatch(
        () => legacyNormalizeMessage(input, defaultRole),
        () => recipeNormalizer.normalizeMessage(input, defaultRole),
        { op: 'normalizeMessage', default_role: defaultRole }
    )
}

export function normalizeMessages(input: unknown, defaultRole: string, tools?: unknown): CompatMessage[] {
    return dispatch(
        () => legacyNormalizeMessages(input, defaultRole, tools),
        () => recipeNormalizer.normalizeMessages(input, defaultRole, tools),
        { op: 'normalizeMessages', default_role: defaultRole, has_tools: tools != null }
    )
}

function dispatch(
    legacy: () => CompatMessage[],
    recipe: () => CompatMessage[],
    context: Record<string, unknown>
): CompatMessage[] {
    const flag = posthog.getFeatureFlagResult(FEATURE_FLAGS.LLM_ANALYTICS_RECIPE_NORMALIZER)
    const useRecipe = !!flag?.enabled

    if (Math.random() >= timingSampleRate(flag?.payload)) {
        return useRecipe ? runRecipe(recipe, legacy) : legacy()
    }
    return shadow(legacy, recipe, useRecipe, context)
}

// The recipe normalizer throws on a coverage gap; fall back so a normalizer bug
// can never break trace rendering.
function runRecipe(recipe: () => CompatMessage[], legacy: () => CompatMessage[]): CompatMessage[] {
    try {
        return recipe()
    } catch (error) {
        posthog.capture('llma recipe normalization fell back', {
            error: error instanceof Error ? error.message : String(error),
        })
        return legacy()
    }
}

function shadow(
    legacy: () => CompatMessage[],
    recipe: () => CompatMessage[],
    useRecipe: boolean,
    context: Record<string, unknown>
): CompatMessage[] {
    const legacyRun = time(legacy)
    const recipeRun = timeSafe(recipe)
    // Strip nullish-valued keys before comparing, so an explicit `undefined`
    // field (e.g. legacy's `tool_call_id: undefined`) counts as equal to an
    // absent one — smooths over quirks in the legacy implementation
    const outputsMatch = recipeRun.ok
        ? objectsEqual(removeUndefinedAndNull(legacyRun.result), removeUndefinedAndNull(recipeRun.result))
        : null

    posthog.capture('llma normalization timed', {
        ...context,
        active_implementation: useRecipe ? 'recipe' : 'legacy',
        legacy_duration_ms: legacyRun.durationMs,
        recipe_duration_ms: recipeRun.ok ? recipeRun.durationMs : null,
        recipe_errored: !recipeRun.ok,
        outputs_match: outputsMatch,
        message_count: legacyRun.result.length,
    })

    return useRecipe && recipeRun.ok ? recipeRun.result : legacyRun.result
}

interface TimedRun {
    result: CompatMessage[]
    durationMs: number
}

type SafeRun = (TimedRun & { ok: true }) | { ok: false }

function time(fn: () => CompatMessage[]): TimedRun {
    const start = performance.now()
    const result = fn()
    return { result, durationMs: roundMs(performance.now() - start) }
}

function timeSafe(fn: () => CompatMessage[]): SafeRun {
    const start = performance.now()
    try {
        const result = fn()
        return { ok: true, result, durationMs: roundMs(performance.now() - start) }
    } catch {
        return { ok: false }
    }
}

function roundMs(ms: number): number {
    return Math.round(ms * 1000) / 1000
}
