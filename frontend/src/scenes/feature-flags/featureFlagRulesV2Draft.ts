import { isEmptyProperty, isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { objectsEqual } from 'lib/utils/objects'

import {
    AnyPropertyFilter,
    FeatureFlagRulesV2DraftConfig,
    FeatureFlagRulesV2DraftExperimentRule,
    FeatureFlagRulesV2DraftHoldout,
    FeatureFlagRulesV2DraftRule,
    FeatureFlagRulesV2ReturnType,
    FeatureFlagRulesV2Variant,
    JsonType,
    PropertyOperator,
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

export function insertedAfter<T>(items: T[], index: number, item: T): T[] {
    return [...items.slice(0, index + 1), item, ...items.slice(index + 1)]
}

/**
 * A condition with no value: the server accepts it, but it never matches. Set and not-set conditions take no value,
 * so they are complete.
 */
export function isIncompleteRulesV2Condition(property: AnyPropertyFilter): boolean {
    return (
        isEmptyProperty(property) &&
        !(
            isPropertyFilterWithOperator(property) &&
            [PropertyOperator.IsSet, PropertyOperator.IsNotSet].includes(property.operator)
        )
    )
}

/** The value a new rule starts with. A string or number has no sensible default, so the user must enter one. */
export function rulesV2InitialValue(returnType: FeatureFlagRulesV2ReturnType): JsonType {
    switch (returnType) {
        case 'boolean':
            return true
        case 'number':
            return null
        case 'object':
            return {}
        default:
            return ''
    }
}

export function rulesV2InitialDefault(returnType: FeatureFlagRulesV2ReturnType): JsonType | null {
    return returnType === 'boolean' ? false : null
}

// A boolean experiment rule starts as control false and test true, a number one as 0 and 1; a string variant
// serves its own key.
function initialVariantValue(returnType: FeatureFlagRulesV2ReturnType, key: string, index: number): JsonType {
    switch (returnType) {
        case 'boolean':
            return index > 0
        case 'number':
            return index
        case 'string':
            return key
        default:
            return rulesV2InitialValue(returnType)
    }
}

export const NEW_TARGETED_RELEASE_RULE: Extract<FeatureFlagRulesV2DraftRule, { rule_type: 'targeted_release' }> = {
    rule_type: 'targeted_release',
    targeting: { properties: [] },
    value: true,
}

// The rollout fields a rule gains when it becomes a percentage rollout; the server assigns its seed.
const NEW_ROLLOUT_FIELDS = {
    rollout_percentage: 0,
    on_rollout_miss: 'continue',
    assignment_algorithm: 'sha1_60_v1',
    assign_by: 'person',
} as const

const NEW_EXPERIMENT_ROLLOUT_FIELDS = { ...NEW_ROLLOUT_FIELDS, rollout_percentage: 100 } as const

export function newRulesV2Rule(
    ruleType: FeatureFlagRulesV2DraftRule['rule_type'],
    returnType: FeatureFlagRulesV2ReturnType
): FeatureFlagRulesV2DraftRule {
    return withRuleType({ ...NEW_TARGETED_RELEASE_RULE, value: rulesV2InitialValue(returnType) }, ruleType, returnType)
}

/**
 * Keeps the rule's identity and shared fields; type-specific fields come and go with the type. A rollout keeps its
 * percentage and miss behaviour between the two randomized types. The seed is dropped, and the server keeps the
 * stored one for as long as the rule stays randomized.
 */
export function withRuleType(
    rule: FeatureFlagRulesV2DraftRule,
    ruleType: FeatureFlagRulesV2DraftRule['rule_type'],
    returnType: FeatureFlagRulesV2ReturnType
): FeatureFlagRulesV2DraftRule {
    if (rule.rule_type === ruleType) {
        return rule
    }
    const { id, targeting, description, metadata } = rule
    const shared = { id, targeting, description, metadata }
    const value = rule.rule_type === 'experiment' ? rulesV2InitialValue(returnType) : rule.value
    const rollout =
        rule.rule_type === 'targeted_release'
            ? null
            : {
                  rollout_percentage: rule.rollout_percentage,
                  on_rollout_miss: rule.on_rollout_miss,
                  assignment_algorithm: rule.assignment_algorithm,
                  assign_by: rule.assign_by,
              }
    switch (ruleType) {
        case 'targeted_release':
            return { ...shared, rule_type: ruleType, value }
        case 'percentage_rollout':
            return { ...shared, rule_type: ruleType, value, ...(rollout ?? NEW_ROLLOUT_FIELDS) }
        case 'experiment':
            return {
                ...shared,
                rule_type: ruleType,
                ...(rollout ?? NEW_EXPERIMENT_ROLLOUT_FIELDS),
                paused: false,
                variants: ['control', 'test'].map((key, index) => ({
                    key,
                    weight: 50,
                    value: initialVariantValue(returnType, key, index),
                })),
            }
    }
}

/**
 * A copy to insert after the original. It has no id, so the server treats it as a new rule, and no seeds, so its users
 * are assigned independently of the original's.
 */
export function duplicatedRule(rule: FeatureFlagRulesV2DraftRule): FeatureFlagRulesV2DraftRule {
    const { id: _id, ...copy } = rule
    if (copy.rule_type === 'targeted_release') {
        return copy
    }
    const { seed: _seed, ...withoutSeed } = copy
    if (withoutSeed.rule_type === 'experiment' && withoutSeed.holdout) {
        return { ...withoutSeed, holdout: { exclusion_percentage: withoutSeed.holdout.exclusion_percentage } }
    }
    return withoutSeed
}

export const NEW_HOLDOUT: FeatureFlagRulesV2DraftHoldout = { exclusion_percentage: 10 }

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

/** The variants' total weight. Two decimals each, so a total in hundredths is exact where a float sum is not. */
export function rulesV2VariantWeightTotal(variants: FeatureFlagRulesV2Variant[]): number {
    return variants.reduce((sum, variant) => sum + Math.round(variant.weight * 100), 0) / 100
}

/** Equal weights in hundredths; the first variants absorb the remainder, so the total is exactly 100. */
export function withEqualWeights(variants: FeatureFlagRulesV2Variant[]): FeatureFlagRulesV2Variant[] {
    const base = Math.floor(10000 / variants.length)
    const remainder = 10000 - base * variants.length
    return variants.map((variant, index) => ({ ...variant, weight: (base + (index < remainder ? 1 : 0)) / 100 }))
}

/**
 * Resets the default, rule and variant values to the new type's starting values.
 * A type change only happens before the flag is created.
 */
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
    switch (returnType) {
        case 'boolean':
            return 'Must be true or false.'
        case 'number':
            return typeof value === 'number' && Number.isFinite(value)
                ? `Must be between -${Number.MAX_SAFE_INTEGER} and ${Number.MAX_SAFE_INTEGER}.`
                : 'Enter a number.'
        case 'object':
            return 'Enter a valid JSON object.'
        default:
            return 'Enter a value.'
    }
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

function experimentErrors(
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
    const total = rulesV2VariantWeightTotal(rule.variants)
    addError(
        errors,
        `${path}.variants`,
        rule.variants.length < MIN_VARIANTS
            ? `Add at least ${MIN_VARIANTS} variants.`
            : rule.variants.length > MAX_VARIANTS
              ? `At most ${MAX_VARIANTS} variants are allowed.`
              : weightsValid && total !== 100
                ? `Variant weights must total 100% (now ${total}%).`
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
            experimentErrors(rule, path, config.return_type, errors)
        }
    })
    if (config.default_value !== null || config.return_type === 'boolean') {
        addError(errors, 'filters.default_value', valueError(config.default_value, config.return_type))
    }
    return errors
}

type RulesV2ReachabilityRule = Pick<FeatureFlagRulesV2DraftRule, 'rule_type' | 'targeting'> &
    Partial<{ rollout_percentage: number; on_rollout_miss: 'continue' | 'return_default'; paused: boolean }>

/** Whether every user a rule matches leaves it with a value, so later rules never see them. */
function claimsEveryMatch(rule: RulesV2ReachabilityRule): boolean {
    if (rule.rule_type === 'targeted_release' || (rule.rule_type === 'experiment' && rule.paused)) {
        return true
    }
    return (rule.rollout_percentage ?? 0) >= 100 || rule.on_rollout_miss === 'return_default'
}

/** Whether `earlier` matches every user `later` matches: its conditions are a subset of the later rule's. */
function matchesEveryoneOf(earlier: RulesV2ReachabilityRule, later: RulesV2ReachabilityRule): boolean {
    return earlier.targeting.properties.every((property) =>
        later.targeting.properties.some((candidate) => objectsEqual(property, candidate))
    )
}

/**
 * For each rule, the index of an earlier rule that claims every user it matches, or null when the rule can serve
 * someone. It only spots shadowing it can prove from the conditions; overlapping conditions are not compared.
 */
export function rulesV2ShadowingRules(rules: RulesV2ReachabilityRule[]): (number | null)[] {
    const claims = rules.map(
        (rule) => claimsEveryMatch(rule) && !rule.targeting.properties.some(isIncompleteRulesV2Condition)
    )
    return rules.map((rule, index) => {
        const shadowing = rules.findIndex(
            (earlier, earlierIndex) => earlierIndex < index && claims[earlierIndex] && matchesEveryoneOf(earlier, rule)
        )
        return shadowing >= 0 ? shadowing : null
    })
}

/** The first rule that claims every user, after which no one falls through to the default step; null if none does. */
export function rulesV2CatchAllRule(rules: RulesV2ReachabilityRule[]): number | null {
    const index = rules.findIndex((rule) => claimsEveryMatch(rule) && rule.targeting.properties.length === 0)
    return index >= 0 ? index : null
}
