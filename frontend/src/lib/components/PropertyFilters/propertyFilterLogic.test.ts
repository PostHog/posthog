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
        it.each([
            {
                desc: 'filter with value',
                filter: eventFilter('$browser', 'Chrome', PropertyOperator.Exact),
                sendAllKeyUpdates: false,
                called: true,
            },
            {
                desc: 'key-only filter without sendAllKeyUpdates',
                filter: eventFilter('$browser'),
                sendAllKeyUpdates: false,
                called: false,
            },
            {
                desc: 'key-only filter with sendAllKeyUpdates',
                filter: eventFilter('$browser'),
                sendAllKeyUpdates: true,
                called: true,
            },
            {
                desc: 'is_set operator without value',
                filter: eventFilter('$browser', undefined, PropertyOperator.IsSet),
                sendAllKeyUpdates: false,
                called: true,
            },
            {
                desc: 'is_not_set operator without value',
                filter: eventFilter('$browser', undefined, PropertyOperator.IsNotSet),
                sendAllKeyUpdates: false,
                called: true,
            },
            {
                desc: 'HogQL filter with only a key',
                filter: { key: "properties.$browser = 'Chrome'", type: PropertyFilterType.HogQL } as AnyPropertyFilter,
                sendAllKeyUpdates: false,
                called: true,
            },
            {
                desc: 'non-HogQL filter with only key and no operator',
                filter: { key: '$browser', type: PropertyFilterType.Event } as AnyPropertyFilter,
                sendAllKeyUpdates: false,
                called: false,
            },
        ])('$desc → onChange called: $called', async ({ filter, sendAllKeyUpdates, called }) => {
            const logic = mountLogic({
                propertyFilters: [{}] as AnyPropertyFilter[],
                sendAllKeyUpdates,
            })
            logic.actions.setFilter(0, filter)

            await expectLogic(logic).toFinishAllListeners()
            expect(onChange).toHaveBeenCalledTimes(called ? 1 : 0)
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
