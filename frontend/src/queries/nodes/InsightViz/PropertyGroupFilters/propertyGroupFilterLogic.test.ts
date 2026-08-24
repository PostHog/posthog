import { expectLogic } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BehavioralEventType, FilterLogicalOperator, PropertyFilterType, PropertyOperator, TimeUnitType } from '~/types'

import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'

describe('propertyGroupFilterLogic', () => {
    let setQuerySpy: jest.Mock

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        setQuerySpy = jest.fn()
    })

    function buildLogic(properties: TrendsQuery['properties']): ReturnType<typeof propertyGroupFilterLogic.build> {
        const query: TrendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            properties: properties ?? undefined,
        }

        const logic = propertyGroupFilterLogic({
            pageKey: 'test',
            query,
            setQuery: setQuerySpy,
        })
        logic.mount()
        return logic
    }

    describe('update listener does not persist empty PropertyGroupFilter structures', () => {
        it('writes undefined when filters are empty', async () => {
            const logic = buildLogic(undefined)

            logic.actions.setFilters({ type: FilterLogicalOperator.And, values: [] })

            await expectLogic(logic).toFinishAllListeners()

            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties).toBeUndefined()
        })

        it('writes undefined when all filter groups have empty values', async () => {
            const logic = buildLogic({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }],
            })

            logic.actions.setFilters({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [] }],
            })

            await expectLogic(logic).toFinishAllListeners()

            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties).toBeUndefined()
        })

        it('writes the filters when they contain real property values', async () => {
            const logic = buildLogic(undefined)

            logic.actions.setFilters({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$browser',
                                value: ['Chrome'],
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ],
            })

            await expectLogic(logic).toFinishAllListeners()

            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties).not.toBeUndefined()
            expect(lastCall.properties.type).toBe(FilterLogicalOperator.And)
            expect(lastCall.properties.values[0].values).toHaveLength(1)
            expect(lastCall.properties.values[0].values[0].key).toBe('$browser')
        })
    })

    describe('addFilterGroupWithFilters', () => {
        // The add-group listeners report usage, so eventUsageLogic has to be mounted
        beforeEach(() => {
            eventUsageLogic.mount()
        })

        const behavioralFilter = {
            type: PropertyFilterType.Behavioral as const,
            value: BehavioralEventType.PerformEvent as const,
            key: '$pageview',
            event_type: 'events' as const,
            time_value: 30,
            time_interval: TimeUnitType.Day,
        }

        it('persists the new group to the query, unlike an empty addFilterGroup', async () => {
            const logic = buildLogic(undefined)

            logic.actions.addFilterGroup()
            await expectLogic(logic).toFinishAllListeners()
            expect(setQuerySpy).not.toHaveBeenCalled()

            logic.actions.addFilterGroupWithFilters([behavioralFilter])
            await expectLogic(logic).toFinishAllListeners()

            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties.values).toHaveLength(2)
            expect(lastCall.properties.values[1].values).toEqual([behavioralFilter])
        })

        it('appends to existing groups rather than replacing them', async () => {
            const logic = buildLogic({
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: PropertyFilterType.Event,
                                key: '$browser',
                                value: ['Chrome'],
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ],
            })

            logic.actions.addFilterGroupWithFilters([behavioralFilter])
            await expectLogic(logic).toFinishAllListeners()

            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties.values).toHaveLength(2)
            expect(lastCall.properties.values[0].values[0].key).toBe('$browser')
            expect(lastCall.properties.values[1].values[0].type).toBe(PropertyFilterType.Behavioral)
        })
    })
})
