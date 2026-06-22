import { AnyPropertyFilter, CohortType, PropertyFilterType, PropertyOperator } from '~/types'

import { createPropertyFilterToken } from './propertyFilterTokenAdapter'

describe('createPropertyFilterToken', () => {
    it.each([
        [
            'status',
            {
                key: 'Status',
                type: PropertyFilterType.ErrorTrackingIssue,
                operator: PropertyOperator.Exact,
                value: 'Active',
            },
            ['Status', '=', 'Active'],
        ],
        [
            'assignee',
            {
                key: 'Assignee',
                type: PropertyFilterType.ErrorTrackingIssue,
                operator: PropertyOperator.Exact,
                value: 'Jane',
            },
            ['Assignee', '=', 'Jane'],
        ],
        [
            'cohort',
            { key: 'id', type: PropertyFilterType.Cohort, operator: PropertyOperator.In, value: 7 },
            ['Cohort', 'in', 'Power users'],
        ],
        [
            'feature flag',
            {
                key: '$active_feature_flags',
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: 'beta-checkout',
                label: 'Feature flag',
            },
            ['Active feature flags', '∋', 'beta-checkout'],
        ],
        [
            'property filter',
            {
                key: '$exception_types',
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: 'TypeError',
            },
            ['Exception type', '∋', 'TypeError'],
        ],
    ])('formats %s tokens', (_name, filter, expectedParts) => {
        const token = createPropertyFilterToken(filter as AnyPropertyFilter, {
            cohortsById: { 7: { id: 7, name: 'Power users' } as CohortType },
        })

        expect(token.parts.map((part) => part.label)).toEqual(expectedParts)
    })

    it.each([
        ['$exception_sources', 'Source'],
        ['$app_version', 'Version'],
    ])('allows adapters to render curated labels for %s', (key, label) => {
        const token = createPropertyFilterToken(
            {
                key,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.IContains,
                value: 'value',
            } as AnyPropertyFilter,
            {
                propertyLabelFormatter: (filter) =>
                    ({ $exception_sources: 'Source', $app_version: 'Version' })[filter.key ?? ''],
            }
        )

        expect(token.parts[0].label).toEqual(label)
    })

    it('uses the operator and optional suffix to keep token ids unique', () => {
        const baseFilter = { key: '$exception_types', type: PropertyFilterType.Event, value: 'TypeError' }
        const exactToken = createPropertyFilterToken({
            ...baseFilter,
            operator: PropertyOperator.Exact,
        } as AnyPropertyFilter)
        const containsToken = createPropertyFilterToken({
            ...baseFilter,
            operator: PropertyOperator.IContains,
        } as AnyPropertyFilter)
        const duplicateToken = createPropertyFilterToken(
            { ...baseFilter, operator: PropertyOperator.Exact } as AnyPropertyFilter,
            { idSuffix: 1 }
        )

        expect(new Set([exactToken.id, containsToken.id, duplicateToken.id]).size).toBe(3)
    })
})
