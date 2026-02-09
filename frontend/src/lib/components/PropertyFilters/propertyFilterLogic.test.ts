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
})
