import {
    allOperatorsMapping,
    chooseOperatorMap,
    isOperatorBetween,
    isOperatorDate,
    isOperatorMulti,
    isOperatorRange,
    isOperatorSemver,
} from 'lib/utils/operators'

import { PropertyOperator, PropertyType } from '~/types'

export interface FilterPickerOperatorOption {
    operator: PropertyOperator
    menuLabel: string
    tokenLabel: string
    metadata: {
        acceptsValue: boolean
        isDate: boolean
        isNumeric: boolean
        isBetween: boolean
        isMultiSelect: boolean
        isSetOperator: boolean
        isSemver: boolean
    }
}

const EXTRA_OPERATOR_LABELS: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.Between]: 'between',
    [PropertyOperator.NotBetween]: 'not between',
    [PropertyOperator.IContainsMulti]: 'contains any of',
    [PropertyOperator.NotIContainsMulti]: "doesn't contain any of",
}

const EXTRA_OPERATOR_SYMBOLS: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.Between]: '↔',
    [PropertyOperator.NotBetween]: '↮',
    [PropertyOperator.IContainsMulti]: '∋',
    [PropertyOperator.NotIContainsMulti]: '∌',
}

// The picker's canonical operator set per type. This is the source of truth for which operators a category
// exposes, overridable by a consumer `operatorAllowlist`. It deliberately does NOT defer to the shared
// `stringOperatorMap`, which leaks semver operators onto every String property — semver is its own category.
export const OPERATOR_POLICY: Partial<Record<PropertyType, PropertyOperator[]>> = {
    [PropertyType.String]: [
        PropertyOperator.Exact,
        PropertyOperator.IsNot,
        PropertyOperator.IContains,
        PropertyOperator.NotIContains,
        PropertyOperator.Regex,
        PropertyOperator.NotRegex,
        PropertyOperator.IsSet,
        PropertyOperator.IsNotSet,
    ],
    [PropertyType.StringArray]: [
        PropertyOperator.Exact,
        PropertyOperator.IsNot,
        PropertyOperator.IContains,
        PropertyOperator.NotIContains,
        PropertyOperator.Regex,
        PropertyOperator.NotRegex,
    ],
    [PropertyType.Semver]: [
        PropertyOperator.SemverEq,
        PropertyOperator.SemverNeq,
        PropertyOperator.SemverGt,
        PropertyOperator.SemverGte,
        PropertyOperator.SemverLt,
        PropertyOperator.SemverLte,
        PropertyOperator.SemverTilde,
        PropertyOperator.SemverCaret,
        PropertyOperator.SemverWildcard,
    ],
    [PropertyType.DateTime]: [
        PropertyOperator.IsDateExact,
        PropertyOperator.IsDateBefore,
        PropertyOperator.IsDateAfter,
        PropertyOperator.IsSet,
        PropertyOperator.IsNotSet,
    ],
    [PropertyType.Numeric]: [
        PropertyOperator.Exact,
        PropertyOperator.IsNot,
        PropertyOperator.GreaterThan,
        PropertyOperator.GreaterThanOrEqual,
        PropertyOperator.LessThan,
        PropertyOperator.LessThanOrEqual,
        PropertyOperator.Between,
        PropertyOperator.NotBetween,
        PropertyOperator.IsSet,
        PropertyOperator.IsNotSet,
    ],
    [PropertyType.Duration]: [
        PropertyOperator.Exact,
        PropertyOperator.GreaterThan,
        PropertyOperator.GreaterThanOrEqual,
        PropertyOperator.LessThan,
        PropertyOperator.LessThanOrEqual,
        PropertyOperator.IsSet,
        PropertyOperator.IsNotSet,
    ],
    [PropertyType.Boolean]: [
        PropertyOperator.Exact,
        PropertyOperator.IsNot,
        PropertyOperator.IsSet,
        PropertyOperator.IsNotSet,
    ],
    [PropertyType.Cohort]: [PropertyOperator.In, PropertyOperator.NotIn],
    [PropertyType.Assignee]: [PropertyOperator.Exact, PropertyOperator.IsNot, PropertyOperator.IsNotSet],
    [PropertyType.Selector]: [PropertyOperator.Exact],
    [PropertyType.Flag]: [PropertyOperator.FlagEvaluatesTo],
}

// The operator a category lands on by default — surfaced first in the list and used when the operator step
// is skipped. A per-property `defaultOperator` overrides this (e.g. a String field that is really a version).
export const DEFAULT_OPERATOR_BY_TYPE: Partial<Record<PropertyType, PropertyOperator>> = {
    [PropertyType.Cohort]: PropertyOperator.In,
    [PropertyType.DateTime]: PropertyOperator.IsDateExact,
    [PropertyType.Semver]: PropertyOperator.SemverEq,
    [PropertyType.Boolean]: PropertyOperator.Exact,
}

// Categories whose default operator dominates so strongly that the picker skips the operator step entirely
// and goes straight to value entry. A property can opt in/out explicitly via `operatorMode`.
export const AUTO_ADVANCE_TYPES = new Set<PropertyType>([PropertyType.Cohort, PropertyType.Boolean])

export function resolveDefaultOperator(
    propertyType: PropertyType | undefined,
    override?: PropertyOperator
): PropertyOperator | undefined {
    return override ?? (propertyType ? DEFAULT_OPERATOR_BY_TYPE[propertyType] : undefined)
}

// Higher-priority labels for the picker. The shared cohortOperatorMap phrases these as "user in" / "user
// not in" (meant to read "user in cohort X"), which makes the picker show the operator as "user"; here the
// operator is just the verb.
const PICKER_LABEL_OVERRIDES: Partial<Record<PropertyOperator, string>> = {
    [PropertyOperator.In]: 'in',
    [PropertyOperator.NotIn]: 'not in',
}

function operatorLabel(operator: PropertyOperator, propertyType?: PropertyType): string {
    return (
        PICKER_LABEL_OVERRIDES[operator] ??
        chooseOperatorMap(propertyType)[operator] ??
        allOperatorsMapping[operator] ??
        EXTRA_OPERATOR_LABELS[operator] ??
        operator
    )
}

export function operatorTokenLabel(operator: PropertyOperator, propertyType?: PropertyType): string {
    const label = operatorLabel(operator, propertyType)
    const firstPart = label.split(' ')[0]
    if (firstPart !== operator) {
        return firstPart
    }
    return EXTRA_OPERATOR_SYMBOLS[operator] ?? firstPart
}

export function createFilterPickerOperatorOption(
    operator: PropertyOperator,
    propertyType?: PropertyType
): FilterPickerOperatorOption {
    // Only is_set/is_not_set take no value. In/NotIn are flagged by isOperatorFlag too, but for cohorts they
    // do take a value (the cohort id), so they must keep their value step.
    const isSetOperator = operator === PropertyOperator.IsSet || operator === PropertyOperator.IsNotSet
    return {
        operator,
        menuLabel: operatorLabel(operator, propertyType),
        tokenLabel: operatorTokenLabel(operator, propertyType),
        metadata: {
            acceptsValue: !isSetOperator,
            isDate: isOperatorDate(operator),
            isNumeric:
                propertyType === PropertyType.Numeric ||
                propertyType === PropertyType.Duration ||
                isOperatorRange(operator),
            isBetween: isOperatorBetween(operator),
            isMultiSelect:
                isOperatorMulti(operator) ||
                operator === PropertyOperator.IContainsMulti ||
                operator === PropertyOperator.NotIContainsMulti,
            isSetOperator,
            isSemver: isOperatorSemver(operator),
        },
    }
}

export function createFilterPickerOperatorOptions(
    propertyType?: PropertyType,
    operatorAllowlist?: PropertyOperator[],
    defaultOperator?: PropertyOperator
): FilterPickerOperatorOption[] {
    // Resolution order: explicit consumer allowlist → the picker's per-type policy → the shared operator map
    // as a last resort for types the policy doesn't cover.
    const operators =
        operatorAllowlist ??
        (propertyType ? OPERATOR_POLICY[propertyType] : undefined) ??
        (Object.keys(chooseOperatorMap(propertyType)) as PropertyOperator[])
    const unique = Array.from(new Set(operators))
    // Surface the default operator first so it is the highlighted/initial choice.
    const ordered =
        defaultOperator && unique.includes(defaultOperator)
            ? [defaultOperator, ...unique.filter((operator) => operator !== defaultOperator)]
            : unique
    return ordered.map((operator) => createFilterPickerOperatorOption(operator, propertyType))
}
