import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { conditionHasFlagDependency, conditionOnlyFlagDependencies } from './releaseConditionEstimateUtils'

const flagDependency: AnyPropertyFilter = {
    type: PropertyFilterType.Flag,
    key: '123',
    operator: PropertyOperator.FlagEvaluatesTo,
    value: 'variant',
}
const personProperty: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.Exact,
    value: ['someone@example.com'],
}
const cohortProperty: AnyPropertyFilter = {
    type: PropertyFilterType.Cohort,
    key: 'id',
    operator: PropertyOperator.In,
    value: 42,
}
const emptyProperty: AnyPropertyFilter = {
    type: PropertyFilterType.Person,
    key: 'email',
    operator: PropertyOperator.Exact,
    value: null,
}

describe('releaseConditionEstimateUtils', () => {
    // Guards the fix for the misleadingly large blast-radius estimate: a condition whose only
    // filter is a flag dependency must be detected so the UI hides the "everyone" count.
    it.each<[string, AnyPropertyFilter[] | null | undefined, boolean, boolean]>([
        ['undefined properties', undefined, false, false],
        ['no properties', [], false, false],
        ['person property only', [personProperty], false, false],
        ['cohort property only', [cohortProperty], false, false],
        ['flag dependency only', [flagDependency], true, true],
        ['flag dependency + person property', [flagDependency, personProperty], true, false],
        ['flag dependency + empty property', [flagDependency, emptyProperty], true, true],
        ['empty property only', [emptyProperty], false, false],
    ])('%s', (_name, properties, hasFlagDependency, onlyFlagDependencies) => {
        expect(conditionHasFlagDependency(properties)).toBe(hasFlagDependency)
        expect(conditionOnlyFlagDependencies(properties)).toBe(onlyFlagDependencies)
    })
})
