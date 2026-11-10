import { CohortType, FilterLogicalOperator } from '~/types'

import { processCohort } from './processCohort'

describe('processCohort', () => {
    it.each([
        {
            name: 'wraps flat criteria into nested group format',
            cohort: {
                id: 3,
                name: 'Flat format cohort',
                count: 0,
                groups: [],
                is_calculating: false,
                is_static: false,
                filters: {
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: 'behavioral',
                                key: 'purchase',
                                value: 'performed_event',
                                event_type: 'events',
                                operator: 'gte',
                                operator_value: 2,
                                time_value: 30,
                                time_interval: 'day',
                                negation: false,
                            },
                        ],
                    },
                },
            } as CohortType,
            expectedType: FilterLogicalOperator.And,
            expectedCriteriaKey: 'purchase',
        },
        {
            name: 'leaves already nested criteria unchanged',
            cohort: {
                id: 4,
                name: 'Nested format cohort',
                count: 0,
                groups: [],
                is_calculating: false,
                is_static: false,
                filters: {
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: 'behavioral',
                                        key: 'purchase',
                                        value: 'performed_event',
                                        event_type: 'events',
                                        explicit_datetime: '-30d',
                                    },
                                ],
                            },
                        ],
                    },
                },
            } as CohortType,
            expectedType: FilterLogicalOperator.And,
            expectedCriteriaKey: 'purchase',
        },
    ])('$name', ({ cohort, expectedType, expectedCriteriaKey }) => {
        const result = processCohort(cohort)
        const group = result.filters.properties.values[0]
        expect(group).toHaveProperty('type', expectedType)
        expect(group).toHaveProperty('values')
        expect((group as any).values).toHaveLength(1)
        expect((group as any).values[0]).toMatchObject({
            type: 'behavioral',
            key: expectedCriteriaKey,
        })
    })

    it('restores a saved person_metadata criterion to editor format (value -> value_property)', () => {
        const cohort = {
            id: 5,
            name: 'First seen cohort',
            count: 0,
            groups: [],
            is_calculating: false,
            is_static: false,
            filters: {
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: 'person_metadata',
                            key: 'created_at',
                            operator: 'is_date_after',
                            value: '2024-01-01',
                            negation: false,
                        },
                    ],
                },
            },
        } as unknown as CohortType

        const result = processCohort(cohort)
        const group = result.filters.properties.values[0]
        // value carries the behavioral row key the editor renders against; the actual
        // filter value moves to value_property. Without this, criteriaToBehavioralFilterType
        // returns the raw date and ROWS[date] is undefined, crashing CohortCriteriaRowBuilder.
        expect((group as any).values[0]).toMatchObject({
            type: 'person_metadata',
            key: 'created_at',
            value: 'have_property',
            value_property: '2024-01-01',
        })
    })

    it('canonicalizes a behavioral value the backend only accepts as an alias', () => {
        const cohort = {
            id: 6,
            name: 'Aliased criterion cohort',
            count: 0,
            groups: [],
            is_calculating: false,
            is_static: false,
            filters: {
                properties: {
                    type: FilterLogicalOperator.And,
                    values: [
                        {
                            type: 'behavioral',
                            key: 'purchase',
                            value: 'performed_event_multiple_times',
                            event_type: 'events',
                            operator: 'gte',
                            operator_value: 2,
                            time_value: 30,
                            time_interval: 'day',
                        },
                    ],
                },
            },
        } as unknown as CohortType

        const result = processCohort(cohort)
        const group = result.filters.properties.values[0]
        // The alias has no ROWS entry, so leaving it verbatim renders the criterion as
        // unsupported even though the backend resolves and queries it. explicit_datetime only
        // gets converted once the value is canonical, and without it validateGroup rejects the
        // row for a missing time window the criterion already carried.
        expect((group as any).values[0]).toMatchObject({
            value: 'performed_event_multiple',
            explicit_datetime: '-30d',
        })
    })
})
