import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { applyKindFilter } from './alertWizardLogic'

describe('applyKindFilter', () => {
    const baseFilters: CyclotronJobFiltersType = {
        events: [{ id: '$health_check_issue_firing', type: 'events' }],
    }

    it.each([
        ['null', null],
        ['an empty array', [] as string[]],
    ])('returns filters unchanged when selectedKinds is %s', (_, kinds) => {
        expect(applyKindFilter(baseFilters, kinds)).toBe(baseFilters)
    })

    it('returns undefined when base filters are undefined', () => {
        expect(applyKindFilter(undefined, ['sdk_outdated'])).toBeUndefined()
    })

    it('adds a kind IN (...) property filter on the first event', () => {
        const result = applyKindFilter(baseFilters, ['sdk_outdated', 'ingestion_warning'])
        expect(result?.events?.[0]).toEqual({
            id: '$health_check_issue_firing',
            type: 'events',
            properties: [
                {
                    key: 'kind',
                    value: ['sdk_outdated', 'ingestion_warning'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        })
    })

    it('replaces any existing properties on the first event', () => {
        const withProps: CyclotronJobFiltersType = {
            events: [
                {
                    id: '$health_check_issue_firing',
                    type: 'events',
                    properties: [
                        {
                            key: 'some_other',
                            value: 'x',
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
            ],
        }
        const result = applyKindFilter(withProps, ['sdk_outdated'])
        expect(result?.events?.[0].properties).toHaveLength(1)
        expect(result?.events?.[0].properties?.[0].key).toBe('kind')
    })

    it('does not touch additional events past the first', () => {
        const twoEvents: CyclotronJobFiltersType = {
            events: [
                { id: '$health_check_issue_firing', type: 'events' },
                { id: '$other_event', type: 'events' },
            ],
        }
        const result = applyKindFilter(twoEvents, ['sdk_outdated'])
        expect(result?.events?.[1]).toEqual({ id: '$other_event', type: 'events' })
    })
})
