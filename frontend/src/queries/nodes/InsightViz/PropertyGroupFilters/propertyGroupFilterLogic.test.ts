import { expectLogic } from 'kea-test-utils'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { propertyGroupFilterLogic } from './propertyGroupFilterLogic'

describe('propertyGroupFilterLogic', () => {
    let setQuerySpy: jest.Mock

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        eventUsageLogic.mount()
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

    describe('addFilterGroup keeps the empty group rendered on dashboard-attached insights', () => {
        it('adds an empty group locally while writing undefined to the query', async () => {
            const logic = buildLogic(undefined)

            logic.actions.addFilterGroup()

            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.values).toHaveLength(1)
            expect(logic.values.filters.values[0].values).toHaveLength(0)
            const lastCall = setQuerySpy.mock.calls[setQuerySpy.mock.calls.length - 1][0]
            expect(lastCall.properties).toBeUndefined()
        })

        it('does not discard the added empty group when the query re-flows with empty properties', async () => {
            const logic = buildLogic(undefined)

            logic.actions.addFilterGroup()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.filters.values).toHaveLength(1)

            // Simulate the dashboard-merged query re-flowing back through GlobalAndOrFilters with a
            // different-but-still-empty properties value, which fires propsChanged.
            propertyGroupFilterLogic({
                pageKey: 'test',
                query: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                    properties: { type: FilterLogicalOperator.And, values: [] },
                },
                setQuery: setQuerySpy,
            })

            expect(logic.values.filters.values).toHaveLength(1)
            expect(logic.values.filters.values[0].values).toHaveLength(0)
        })
    })

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
})
