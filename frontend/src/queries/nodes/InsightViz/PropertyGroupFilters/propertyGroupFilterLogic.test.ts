import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { EventPropertyFilter, FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

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

        it('writes only the filter groups that contain real property values', async () => {
            const logic = buildLogic(undefined)

            logic.actions.setFilters({
                type: FilterLogicalOperator.And,
                values: [
                    { type: FilterLogicalOperator.And, values: [] },
                    { type: FilterLogicalOperator.Or, values: [] },
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
            expect(lastCall.properties.values).toHaveLength(1)
            expect(lastCall.properties.values[0].values).toHaveLength(1)
            expect(lastCall.properties.values[0].values[0].key).toBe('$browser')
        })

        it('keeps a just-added filter group in the editor until it has a filter', async () => {
            const browserFilter = (browser: string): EventPropertyFilter => ({
                type: PropertyFilterType.Event,
                key: '$browser',
                value: [browser],
                operator: PropertyOperator.Exact,
            })
            const logic = buildLogic({
                type: FilterLogicalOperator.And,
                values: [{ type: FilterLogicalOperator.And, values: [browserFilter('Chrome')] }],
            })
            // The insight editor passes each written query back in as props.
            setQuerySpy.mockImplementation((query) =>
                propertyGroupFilterLogic({ pageKey: 'test', query, setQuery: setQuerySpy })
            )

            logic.actions.addFilterGroup()
            logic.actions.setPropertyFilters([browserFilter('Firefox')], 0)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.filters.values.map((group) => group.values)).toEqual([[browserFilter('Firefox')], []])
            expect(setQuerySpy.mock.lastCall[0].properties.values).toHaveLength(1)

            logic.actions.setPropertyFilters([browserFilter('Safari')], 1)
            await expectLogic(logic).toFinishAllListeners()

            expect(setQuerySpy.mock.lastCall[0].properties.values).toHaveLength(2)
        })
    })
})
