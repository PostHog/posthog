import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { nestedFilterLogic } from './nestedFilterLogic'

describe('nestedFilterLogic', () => {
    const browserFilter: AnyPropertyFilter = {
        key: '$browser',
        value: 'Chrome',
        operator: PropertyOperator.Exact,
        type: PropertyFilterType.Event,
    }

    function mountNestedFilter(initiallyVisible: boolean): ReturnType<typeof nestedFilterLogic.build> {
        const logic = nestedFilterLogic({
            groupFilterUuid: 'group-uuid',
            nestedIndex: 0,
            typeKey: 'nested_visibility_test',
            groupIndex: 0,
            initiallyVisible,
        })
        logic.mount()
        return logic
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: [] },
                '/api/projects/:team/event_definitions/': { results: [] },
            },
        })
        initKeaTests()
    })

    it('expands a nested row that gains property filters', async () => {
        const logic = mountNestedFilter(false)

        await expectLogic(logic, () => {
            logic.actions.updateFilterProperty({ index: 0, properties: [browserFilter] })
        }).toMatchValues({ entityFilterVisible: { 0: true } })
    })

    it('keeps a nested row collapsed after the user hides its filters', async () => {
        const logic = mountNestedFilter(false)

        await expectLogic(logic, () => {
            logic.actions.setEntityFilterVisibility(0, false)
            logic.actions.updateFilterProperty({ index: 0, properties: [browserFilter] })
        }).toMatchValues({ entityFilterVisible: { 0: false } })
    })

    it('keeps a nested row expanded after the user removes its last filter', async () => {
        const logic = mountNestedFilter(true)

        await expectLogic(logic, () => {
            logic.actions.updateFilterProperty({ index: 0, properties: [] })
        }).toMatchValues({ entityFilterVisible: { 0: true } })
    })
})
