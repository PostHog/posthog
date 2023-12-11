import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'

describe('rollingDateRangeFilterLogic', () => {
    let logic: ReturnType<typeof rollingDateRangeFilterLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    it('has -3d as default value', () => {
        logic = rollingDateRangeFilterLogic({})
        logic.mount()
        expectLogic(logic, () => {}).toMatchValues({
            value: '-3d',
        })
    })

    it('correctly sets the value', () => {
        logic = rollingDateRangeFilterLogic({})
        logic.mount()
        expectLogic(logic, () => {
            logic.actions.increaseCounter()
            logic.actions.setDateOption('months')
        }).toMatchValues({
            value: '-4m',
        })
        expectLogic(logic, () => {
            logic.actions.decreaseCounter()
            logic.actions.setDateOption('quarters')
        }).toMatchValues({
            value: '-3q',
        })
        expectLogic(logic, () => {
            logic.actions.setCounter(6)
            logic.actions.setDateOption('days')
        }).toMatchValues({
            value: '-6d',
        })
    })

    it('cannot set the date higher than the max', () => {
        logic = rollingDateRangeFilterLogic({ max: 6 })
        logic.mount()
        expectLogic(logic, () => {
            logic.actions.setCounter(6)
            logic.actions.setDateOption('days')
        }).toMatchValues({
            value: '-6d',
        })
        expectLogic(logic, () => {
            logic.actions.setCounter(13)
        }).toMatchValues({
            value: '-6d',
        })
        expectLogic(logic, () => {
            logic.actions.increaseCounter()
        }).toMatchValues({
            value: '-6d',
        })
    })
})
