import { stripSessionIds, summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'

import {
    CohortType,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
} from '~/types'

describe('summarizePlaylistFilters()', () => {
    const cohortIdsMapped: Partial<Record<CohortType['id'], CohortType>> = {
        1: {
            id: 1,
            name: 'New Yorkers',
            filters: { properties: { id: '1', type: FilterLogicalOperator.Or, values: [] } },
            groups: [],
        },
    }

    it('summarizes a playlist with four events and an action', () => {
        expect(
            summarizePlaylistFilters(
                [
                    // events
                    {
                        type: 'events',
                        id: '$pageview',
                        name: '$pageview',
                        order: 0,
                    },
                    {
                        type: 'events',
                        id: '$rageclick',
                        name: '$rageclick',
                        order: 1,
                    },
                    {
                        type: 'events',
                        id: '$pageview',
                        name: '$pageview',
                        order: 4,
                    },
                    {
                        type: 'events',
                        id: '$autocapture',
                        name: '$autocapture',
                        order: 5,
                    },
                    // actions
                    {
                        type: 'actions',
                        id: 1,
                        name: 'Random action',
                        order: 2,
                    },
                ],
                cohortIdsMapped
            )
        ).toEqual('Pageview & Rageclick & Random action & Pageview & Autocapture')
    })

    it('summarizes a playlist with one event, one PH person property and one custom property', () => {
        expect(
            summarizePlaylistFilters(
                [
                    // events
                    {
                        type: 'events',
                        id: '$pageview',
                        name: '$pageview',
                        order: 0,
                    },
                    // properties
                    {
                        key: '$initial_browser',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                    {
                        key: 'custom_property',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.IContains,
                        value: 'blah',
                    },
                ],
                cohortIdsMapped
            )
        ).toEqual('Pageview, on Initial browser = Chrome & custom_property ∋ blah')
    })

    it('summarizes a playlist with one event and one cohort', () => {
        expect(
            summarizePlaylistFilters(
                [
                    // events
                    {
                        type: 'events',
                        id: '$pageview',
                        name: '$pageview',
                        order: 0,
                    },
                    // properties
                    {
                        key: 'id',
                        type: PropertyFilterType.Cohort,
                        operator: PropertyOperator.In,
                        value: 1,
                    },
                ],
                cohortIdsMapped
            )
        ).toEqual('Pageview, on cohorts: New Yorkers')
    })

    it('summarizes a playlist with one property', () => {
        expect(
            summarizePlaylistFilters(
                [
                    {
                        key: 'id',
                        type: PropertyFilterType.Cohort,
                        operator: PropertyOperator.In,
                        value: 1,
                    },
                ],
                cohortIdsMapped
            )
        ).toEqual('cohorts: New Yorkers')
    })

    it('all together', () => {
        expect(
            summarizePlaylistFilters(
                [
                    // events
                    {
                        type: 'events',
                        id: '$pageview',
                        name: '$pageview',
                        order: 0,
                    },
                    // actions
                    {
                        type: 'actions',
                        id: 1,
                        name: 'Random action',
                        order: 2,
                    },
                    // properties
                    {
                        key: '$initial_browser',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: 'Chrome',
                    },
                    {
                        key: 'custom_property',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.IContains,
                        value: 'blah',
                    },
                    {
                        key: 'id',
                        type: PropertyFilterType.Cohort,
                        operator: PropertyOperator.In,
                        value: 1,
                    },
                ],
                cohortIdsMapped
            )
        ).toEqual(
            'Pageview & Random action, on Initial browser = Chrome & custom_property ∋ blah & cohorts: New Yorkers'
        )
    })
})

describe('stripSessionIds()', () => {
    const baseFilters: Partial<RecordingUniversalFilters> = {
        date_from: '-30d',
        date_to: null,
        filter_test_accounts: false,
        filter_group: {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            key: 'id',
                            type: PropertyFilterType.Cohort,
                            operator: PropertyOperator.In,
                            value: 247048,
                        },
                    ],
                },
            ],
        },
    }

    it('strips session ids, leaves other filter fields untouched', () => {
        const result = stripSessionIds({
            ...baseFilters,
            session_ids: ['019d68e1-1165-7cf9-b87b-759fe1604d99'],
        })
        expect(result).toEqual(baseFilters)
    })

    it('returns the same reference when session_ids is absent', () => {
        // no allocation, no mutation — cheap no-op path
        const input = { ...baseFilters }
        expect(stripSessionIds(input)).toBe(input)
    })

    it.each([
        ['undefined', undefined],
        ['null', null],
    ])('passes %s through unchanged', (_name, input) => {
        expect(stripSessionIds(input as any)).toBe(input)
    })
})
