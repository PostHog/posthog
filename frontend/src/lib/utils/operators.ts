import { PropertyOperator, PropertyType } from '~/types'

export const genericOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    gt: '> greater than',
    gte: '≥ greater than or equal',
    lt: '< less than',
    lte: '≤ less than or equal',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const stringOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
    semver_eq: '= equals (semver)',
    semver_neq: '≠ not equal (semver)',
    semver_gt: '> greater than (semver)',
    semver_gte: '≥ greater than or equal (semver)',
    semver_lt: '< less than (semver)',
    semver_lte: '≤ less than or equal (semver)',
    semver_tilde: '~ tilde range (semver)',
    semver_caret: '^ caret range (semver)',
    semver_wildcard: '* wildcard (semver)',
}

export const stringArrayOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    icontains: '∋ contains',
    not_icontains: "∌ doesn't contain",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
}

export const numericOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    regex: '∼ matches regex',
    not_regex: "≁ doesn't match regex",
    gt: '> greater than',
    gte: '≥ greater than or equal',
    lt: '< less than',
    lte: '≤ less than or equal',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const dateTimeOperatorMap: Record<string, string> = {
    is_date_exact: '= equals',
    is_date_before: '< before',
    is_date_after: '> after',
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const booleanOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
    is_set: '✓ is set',
    is_not_set: '✕ is not set',
}

export const durationOperatorMap: Record<string, string> = {
    gt: '> greater than',
    lt: '< less than',
}

export const selectorOperatorMap: Record<string, string> = {
    exact: '= equals',
    is_not: "≠ doesn't equal",
}

export const cohortOperatorMap: Record<string, string> = {
    in: 'user in',
    not_in: 'user not in',
}

export const featureFlagOperatorMap: Record<string, string> = {
    flag_evaluates_to: '= evaluates to',
}

export const stickinessOperatorMap: Record<string, string> = {
    exact: '= exactly',
    gte: '≥ at least',
    lte: '≤ at most (but at least once)',
}

export const cleanedPathOperatorMap: Record<string, string> = {
    is_cleaned_path_exact: '= equals',
}

export const semverOperatorMap: Record<string, string> = {
    semver_eq: '= equals (semver)',
    semver_neq: '≠ not equal (semver)',
    semver_gt: '> greater than (semver)',
    semver_gte: '≥ greater than or equal (semver)',
    semver_lt: '< less than (semver)',
    semver_lte: '≤ less than or equal (semver)',
    semver_tilde: '~ tilde range (semver)',
    semver_caret: '^ caret range (semver)',
    semver_wildcard: '* wildcard (semver)',
}

export const assigneeOperatorMap: Record<string, string> = {
    exact: '= is',
    is_not: '≠ is not',
    is_not_set: '✕ is not set',
}

export const allOperatorsMapping: Record<string, string> = {
    ...assigneeOperatorMap,
    ...stickinessOperatorMap,
    ...dateTimeOperatorMap,
    ...semverOperatorMap,
    ...stringArrayOperatorMap,
    ...numericOperatorMap,
    ...genericOperatorMap,
    ...booleanOperatorMap,
    ...durationOperatorMap,
    ...selectorOperatorMap,
    ...cohortOperatorMap,
    ...featureFlagOperatorMap,
    ...cleanedPathOperatorMap,
    ...stringOperatorMap,
    // slight overkill to spread all of these into the map
    // but gives freedom for them to diverge more over time
}

const operatorMappingChoice: Record<keyof typeof PropertyType, Record<string, string>> = {
    DateTime: dateTimeOperatorMap,
    String: stringOperatorMap,
    Numeric: numericOperatorMap,
    Boolean: booleanOperatorMap,
    Duration: durationOperatorMap,
    Selector: selectorOperatorMap,
    Cohort: cohortOperatorMap,
    Flag: featureFlagOperatorMap,
    Assignee: assigneeOperatorMap,
    StringArray: stringArrayOperatorMap,
    Semver: semverOperatorMap,
}

export function chooseOperatorMap(propertyType: PropertyType | undefined): Record<string, string> {
    let choice = genericOperatorMap
    if (propertyType) {
        choice = operatorMappingChoice[propertyType] || genericOperatorMap
    }
    return choice
}

export function isOperatorMulti(operator: PropertyOperator): boolean {
    return [
        PropertyOperator.Exact,
        PropertyOperator.IsNot,
        PropertyOperator.IContainsMulti,
        PropertyOperator.NotIContainsMulti,
    ].includes(operator)
}

export function isOperatorFlag(operator: PropertyOperator): boolean {
    // these filter operators can only be just set, no additional parameter
    return [PropertyOperator.IsSet, PropertyOperator.IsNotSet, PropertyOperator.In, PropertyOperator.NotIn].includes(
        operator
    )
}

export function isOperatorCohort(operator: PropertyOperator): boolean {
    // these filter operators use value different ( to represent the number of the cohort )
    return [PropertyOperator.In, PropertyOperator.NotIn].includes(operator)
}

export function isOperatorRegex(operator: PropertyOperator): boolean {
    return [PropertyOperator.Regex, PropertyOperator.NotRegex].includes(operator)
}

export function isOperatorSemver(operator: PropertyOperator): boolean {
    return [
        PropertyOperator.SemverEq,
        PropertyOperator.SemverNeq,
        PropertyOperator.SemverGt,
        PropertyOperator.SemverGte,
        PropertyOperator.SemverLt,
        PropertyOperator.SemverLte,
        PropertyOperator.SemverTilde,
        PropertyOperator.SemverCaret,
        PropertyOperator.SemverWildcard,
    ].includes(operator)
}

export function isOperatorRange(operator: PropertyOperator): boolean {
    return [
        PropertyOperator.GreaterThan,
        PropertyOperator.GreaterThanOrEqual,
        PropertyOperator.LessThan,
        PropertyOperator.LessThanOrEqual,
        PropertyOperator.Between,
        PropertyOperator.NotBetween,
    ].includes(operator)
}

export function isOperatorDate(operator: PropertyOperator): boolean {
    return [PropertyOperator.IsDateBefore, PropertyOperator.IsDateAfter, PropertyOperator.IsDateExact].includes(
        operator
    )
}

export function isOperatorBetween(operator: PropertyOperator): boolean {
    return [PropertyOperator.Between, PropertyOperator.NotBetween].includes(operator)
}
