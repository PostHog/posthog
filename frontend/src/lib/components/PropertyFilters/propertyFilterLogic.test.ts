import { expectLogic } from 'kea-test-utils'

import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

const eventFilter = (key: string, value?: string, operator?: PropertyOperator): AnyPropertyFilter =>
    ({
        key,
        type: PropertyFilterType.Event,
        ...(value !== undefined ? { value } : {}),
        ...(operator !== undefined ? { operator } : {}),
    }) as AnyPropertyFilter

describe('propertyFilterLogic', () => {
    let onChange: jest.Mock

    beforeEach(() => {
        useMocks({})
        initKeaTests()
        onChange = jest.fn()
    })

    function mountLogic(
        overrides: { propertyFilters?: AnyPropertyFilter[]; sendAllKeyUpdates?: boolean } = {}
    ): ReturnType<typeof propertyFilterLogic.build> {
        const logic = propertyFilterLogic({
            pageKey: 'test',
            onChange,
            ...overrides,
        })
        logic.mount()
        return logic
    }

    describe('remove appends empty PropertyFilter correctly', () => {
        it('leaves a single empty PropertyFilter when all filters are removed', () => {
            const logic = mountLogic({
                propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact)],
            })
            logic.actions.remove(0)
            expect(logic.values.filters).toEqual([{}])
        })

        it('appends empty PropertyFilter after removing if the last remaining filter is valid', () => {
            const logic = mountLogic({
                propertyFilters: [
                    eventFilter('$browser', 'Chrome', PropertyOperator.Exact),
                    eventFilter('$os', 'Mac', PropertyOperator.Exact),
                ],
            })
            logic.actions.remove(0)
            expect(logic.values.filters).toHaveLength(2)
            expect(logic.values.filters[0].key).toBe('$os')
            expect(Object.keys(logic.values.filters[1])).toHaveLength(0)
        })

        it('does not double-append if the last filter is already empty', () => {
            const logic = mountLogic({
                propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact), {} as AnyPropertyFilter],
            })
            logic.actions.remove(0)
            expect(logic.values.filters).toEqual([{}])
        })
    })

    describe('setFilter conditionally calls onChange', () => {
        async function setFilterAndCheck(filter: AnyPropertyFilter, sendAllKeyUpdates: boolean): Promise<jest.Mock> {
            const logic = mountLogic({
                propertyFilters: [{}] as AnyPropertyFilter[],
                sendAllKeyUpdates,
            })
            logic.actions.setFilter(0, filter)
            await expectLogic(logic).toFinishAllListeners()
            return onChange
        }

        it('calls onChange for a filter with a value', async () => {
            const cb = await setFilterAndCheck(eventFilter('$browser', 'Chrome', PropertyOperator.Exact), false)
            expect(cb).toHaveBeenCalledTimes(1)
        })

        it('does not call onChange for a key-only filter', async () => {
            const cb = await setFilterAndCheck(eventFilter('$browser'), false)
            expect(cb).not.toHaveBeenCalled()
        })

        it('calls onChange for a key-only filter when sendAllKeyUpdates is true', async () => {
            const cb = await setFilterAndCheck(eventFilter('$browser'), true)
            expect(cb).toHaveBeenCalledTimes(1)
        })

        it('calls onChange for is_set operator without a value', async () => {
            const cb = await setFilterAndCheck(eventFilter('$browser', undefined, PropertyOperator.IsSet), false)
            expect(cb).toHaveBeenCalledTimes(1)
        })

        it('calls onChange for is_not_set operator without a value', async () => {
            const cb = await setFilterAndCheck(eventFilter('$browser', undefined, PropertyOperator.IsNotSet), false)
            expect(cb).toHaveBeenCalledTimes(1)
        })

        it('calls onChange for a HogQL filter with only a key', async () => {
            const filter = {
                key: "properties.$browser = 'Chrome'",
                type: PropertyFilterType.HogQL,
            } as AnyPropertyFilter
            const cb = await setFilterAndCheck(filter, false)
            expect(cb).toHaveBeenCalledTimes(1)
        })

        it('does not call onChange for a non-HogQL filter with only a key and no operator', async () => {
            const filter = { key: '$browser', type: PropertyFilterType.Event } as AnyPropertyFilter
            const cb = await setFilterAndCheck(filter, false)
            expect(cb).not.toHaveBeenCalled()
        })
    })

    describe('filter IDs are stable across mutations', () => {
        describe('remove', () => {
            it('preserves IDs of filters that were not removed', () => {
                const logic = mountLogic({
                    propertyFilters: [
                        eventFilter('$browser', 'Chrome', PropertyOperator.Exact),
                        eventFilter('$os', 'Mac', PropertyOperator.Exact),
                        eventFilter('$device', 'Mobile', PropertyOperator.Exact),
                    ],
                })
                const [_, osId, deviceId] = logic.values.filterIds

                logic.actions.remove(0)

                expect(logic.values.filterIds[0]).toBe(osId)
                expect(logic.values.filterIds[1]).toBe(deviceId)
            })
        })

        describe('setFilter', () => {
            it('keeps the same ID when updating an existing position', () => {
                const logic = mountLogic({
                    propertyFilters: [
                        eventFilter('$browser', 'Chrome', PropertyOperator.Exact),
                        eventFilter('$os', 'Mac', PropertyOperator.Exact),
                    ],
                })
                const idsBefore = [...logic.values.filterIds]

                logic.actions.setFilter(0, eventFilter('$country', 'US', PropertyOperator.Exact))

                expect(logic.values.filterIds).toEqual(idsBefore)
            })

            it('assigns a new ID when appending beyond current length', () => {
                const logic = mountLogic({
                    propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact)],
                })
                const [browserId] = logic.values.filterIds

                logic.actions.setFilter(1, eventFilter('$os', 'Mac', PropertyOperator.Exact))

                expect(logic.values.filterIds[0]).toBe(browserId)
                expect(logic.values.filterIds).toHaveLength(2)
                expect(logic.values.filterIds[1]).not.toBe(browserId)
            })
        })

        describe('setFilters', () => {
            it('preserves IDs at positions that overlap with current items', () => {
                const logic = mountLogic({
                    propertyFilters: [
                        eventFilter('$browser', 'Chrome', PropertyOperator.Exact),
                        eventFilter('$os', 'Mac', PropertyOperator.Exact),
                    ],
                })
                const [browserId, osId] = logic.values.filterIds

                logic.actions.setFilters([
                    eventFilter('$country', 'US', PropertyOperator.Exact),
                    eventFilter('$city', 'SF', PropertyOperator.Exact),
                    eventFilter('$region', 'CA', PropertyOperator.Exact),
                ])

                expect(logic.values.filterIds[0]).toBe(browserId)
                expect(logic.values.filterIds[1]).toBe(osId)
                expect(logic.values.filterIds[2]).not.toBe(browserId)
                expect(logic.values.filterIds[2]).not.toBe(osId)
            })

            it('returns the same state reference when content is equal', () => {
                const logic = mountLogic({
                    propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact)],
                })
                const stateBefore = logic.values._filtersState

                logic.actions.setFilters([eventFilter('$browser', 'Chrome', PropertyOperator.Exact)])

                expect(logic.values._filtersState).toBe(stateBefore)
            })
        })

        describe('filterIdsWithNew', () => {
            it('has the same length as filtersWithNew after each mutation', () => {
                const logic = mountLogic({
                    propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact)],
                })
                expect(logic.values.filterIdsWithNew).toHaveLength(logic.values.filtersWithNew.length)

                logic.actions.remove(0)
                expect(logic.values.filterIdsWithNew).toHaveLength(logic.values.filtersWithNew.length)

                logic.actions.setFilter(0, eventFilter('$os', 'Mac', PropertyOperator.Exact))
                expect(logic.values.filterIdsWithNew).toHaveLength(logic.values.filtersWithNew.length)
            })
        })
    })

    describe('onChange receives cleaned filters', () => {
        it('strips empty/invalid filters before calling onChange', async () => {
            const logic = mountLogic({
                propertyFilters: [eventFilter('$browser', 'Chrome', PropertyOperator.Exact), {} as AnyPropertyFilter],
                sendAllKeyUpdates: true,
            })

            logic.actions.setFilter(0, eventFilter('$browser', 'Firefox', PropertyOperator.Exact))

            await expectLogic(logic).toFinishAllListeners()
            const calledWith = onChange.mock.calls[0][0]
            expect(calledWith).toHaveLength(1)
            expect(calledWith[0]).toMatchObject({ key: '$browser', value: 'Firefox' })
        })
    })
})
