import {
    FeatureFlagRulesV2DraftConfig,
    FeatureFlagRulesV2DraftExperimentRule,
    FeatureFlagRulesV2ReturnType,
    FeatureFlagRulesV2Variant,
    JsonType,
} from '~/types'

import { isRulesV2Value } from 'products/feature_flags/frontend/featureFlagConfigFormat'

export const MIN_VARIANTS = 2
export const MAX_VARIANTS = 20
const VARIANT_KEY = /^[a-zA-Z0-9_-]+$/
// `String` gives the shortest decimal that round-trips the number, so 33.33 passes and 1e-7 does not.
const AT_MOST_TWO_DECIMALS = /^\d+(\.\d{1,2})?$/

export function moved<T>(items: T[], from: number, to: number): T[] {
    const result = [...items]
    result.splice(to, 0, ...result.splice(from, 1))
    return result
}

/** The value a new rule starts with. A string has no sensible default, so the user must enter one. */
export function rulesV2InitialValue(returnType: FeatureFlagRulesV2ReturnType): JsonType {
    return returnType === 'boolean' ? true : ''
}

export function rulesV2InitialDefault(returnType: FeatureFlagRulesV2ReturnType): JsonType | null {
    return returnType === 'boolean' ? false : null
}

// A boolean split starts as control false and test true; a string variant serves its own key.
function initialVariantValue(returnType: FeatureFlagRulesV2ReturnType, key: string, index: number): JsonType {
    return returnType === 'boolean' ? index > 0 : key
}

export function newVariantSplitFields(
    returnType: FeatureFlagRulesV2ReturnType
): Pick<FeatureFlagRulesV2DraftExperimentRule, 'experiment_id' | 'paused' | 'variants'> {
    return {
        experiment_id: null,
        paused: false,
        variants: ['control', 'test'].map((key, index) => ({
            key,
            weight: 50,
            value: initialVariantValue(returnType, key, index),
        })),
    }
}

export function newVariant(returnType: FeatureFlagRulesV2ReturnType, index: number): FeatureFlagRulesV2Variant {
    return { key: '', weight: 0, value: initialVariantValue(returnType, '', index) }
}

/** On a string flag, a variant that serves its own key keeps doing so when the key changes. */
export function withVariantKey(
    variant: FeatureFlagRulesV2Variant,
    key: string,
    returnType: FeatureFlagRulesV2ReturnType
): FeatureFlagRulesV2Variant {
    const followsKey = returnType === 'string' && variant.value === variant.key
    return { ...variant, key, ...(followsKey ? { value: key } : {}) }
}

/** Equal weights in hundredths; the first variants absorb the remainder, so the total is exactly 100. */
export function withEqualWeights(variants: FeatureFlagRulesV2Variant[]): FeatureFlagRulesV2Variant[] {
    const base = Math.floor(10000 / variants.length)
    const remainder = 10000 - base * variants.length
    return variants.map((variant, index) => ({ ...variant, weight: (base + (index < remainder ? 1 : 0)) / 100 }))
}

/** Every variant value follows the new return type; a type change only happens before the flag is created. */
export function withReturnType(
    config: FeatureFlagRulesV2DraftConfig,
    returnType: FeatureFlagRulesV2ReturnType
): FeatureFlagRulesV2DraftConfig {
    if (config.return_type === returnType) {
        return config
    }
    return {
        ...config,
        return_type: returnType,
        default_value: rulesV2InitialDefault(returnType),
        rules: config.rules.map((rule) =>
            rule.rule_type === 'experiment'
                ? {
                      ...rule,
                      variants: rule.variants.map((variant, index) => ({
                          ...variant,
                          value: initialVariantValue(returnType, variant.key, index),
                      })),
                  }
                : { ...rule, value: rulesV2InitialValue(returnType) }
        ),
    }
}

function percentageError(value: unknown): string | null {
    if (typeof value !== 'number' || !(value >= 0 && value <= 100)) {
        return 'Must be between 0 and 100.'
    }
    return AT_MOST_TWO_DECIMALS.test(String(value)) ? null : 'Must have at most two decimal places.'
}

function valueError(value: unknown, returnType: FeatureFlagRulesV2ReturnType): string | null {
    if (isRulesV2Value(value, returnType)) {
        return null
    }
    return returnType === 'boolean' ? 'Must be true or false.' : 'Enter a value.'
}

function variantKeyError(key: string, seen: Set<string>): string | null {
    if (!key) {
        return 'Enter a key.'
    }
    if (!VARIANT_KEY.test(key)) {
        return 'Only letters, numbers, hyphens (-) and underscores (_) are allowed.'
    }
    return seen.has(key) ? 'Variant keys must be unique.' : null
}

function variantSplitErrors(
    rule: FeatureFlagRulesV2DraftExperimentRule,
    path: string,
    returnType: FeatureFlagRulesV2ReturnType,
    errors: Record<string, string>
): void {
    const seen = new Set<string>()
    let weightsValid = true
    rule.variants.forEach((variant, index) => {
        const variantPath = `${path}.variants[${index}]`
        addError(errors, `${variantPath}.key`, variantKeyError(variant.key, seen))
        seen.add(variant.key)
        const weightError = percentageError(variant.weight)
        weightsValid &&= weightError === null
        addError(errors, `${variantPath}.weight`, weightError)
        addError(errors, `${variantPath}.value`, valueError(variant.value, returnType))
    })
    // Two decimals each, so a total in hundredths is exact where a float sum is not.
    const total = rule.variants.reduce((sum, variant) => sum + Math.round(variant.weight * 100), 0)
    addError(
        errors,
        `${path}.variants`,
        rule.variants.length < MIN_VARIANTS
            ? `Add at least ${MIN_VARIANTS} variants.`
            : rule.variants.length > MAX_VARIANTS
              ? `At most ${MAX_VARIANTS} variants are allowed.`
              : weightsValid && total !== 10000
                ? `Variant weights must total 100% (now ${total / 100}%).`
                : null
    )
    if (rule.holdout) {
        addError(errors, `${path}.holdout.exclusion_percentage`, percentageError(rule.holdout.exclusion_percentage))
    }
}

function addError(errors: Record<string, string>, field: string, error: string | null): void {
    if (error) {
        errors[field] = error
    }
}

/**
 * What the client can check with certainty before a save, keyed by the path the server reports the same error on.
 * The server stays the authority: it also checks what is not repeated here, such as reserved values.
 */
export function rulesV2DraftErrors(config: FeatureFlagRulesV2DraftConfig): Record<string, string> {
    const errors: Record<string, string> = {}
    config.rules.forEach((rule, index) => {
        const path = `filters.rules[${index}]`
        if (rule.rule_type !== 'experiment') {
            addError(errors, `${path}.value`, valueError(rule.value, config.return_type))
        }
        if (rule.rule_type !== 'targeted_release') {
            addError(errors, `${path}.rollout_percentage`, percentageError(rule.rollout_percentage))
        }
        if (rule.rule_type === 'experiment') {
            variantSplitErrors(rule, path, config.return_type, errors)
        }
    })
    return errors
}
