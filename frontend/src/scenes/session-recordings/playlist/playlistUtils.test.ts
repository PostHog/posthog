import { summarizePlaylistFilters } from 'scenes/session-recordings/playlist/playlistUtils'

import { CohortType, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

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
                {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                        {
                            id: '$rageclick',
                            name: '$rageclick',
                            order: 1,
                        },
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 4,
                        },
                        {
                            id: '$autocapture',
                            name: '$autocapture',
                            order: 5,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            order: 2,
                        },
                    ],
                },
                cohortIdsMapped
            )
        ).toEqual('Pageview & Rageclick & Random action & Pageview & Autocapture')
    })

    it('summarizes a playlist with one event, one PH person property and one custom property', () => {
        expect(
            summarizePlaylistFilters(
                {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                    ],
                    properties: [
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
                },
                cohortIdsMapped
            )
        ).toEqual('Pageview, on Initial Browser = Chrome & custom_property ∋ blah')
    })

    it('summarizes a playlist with one event and one cohort', () => {
        expect(
            summarizePlaylistFilters(
                {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                    ],
                    properties: [
                        {
                            key: 'id',
                            type: PropertyFilterType.Cohort,
                            value: 1,
                        },
                    ],
                },
                cohortIdsMapped
            )
        ).toEqual('Pageview, on cohorts: New Yorkers')
    })

    it('summarizes a playlist with one property', () => {
        expect(
            summarizePlaylistFilters(
                {
                    properties: [
                        {
                            key: 'id',
                            type: PropertyFilterType.Cohort,
                            value: 1,
                        },
                    ],
                },
                cohortIdsMapped
            )
        ).toEqual('cohorts: New Yorkers')
    })

    it('all together', () => {
        expect(
            summarizePlaylistFilters(
                {
                    events: [
                        {
                            id: '$pageview',
                            name: '$pageview',
                            order: 0,
                        },
                    ],
                    actions: [
                        {
                            id: 1,
                            name: 'Random action',
                            order: 2,
                        },
                    ],
                    properties: [
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
                            value: 1,
                        },
                    ],
                },
                cohortIdsMapped
            )
        ).toEqual(
            'Pageview & Random action, on Initial Browser = Chrome & custom_property ∋ blah & cohorts: New Yorkers'
        )
    })
})
