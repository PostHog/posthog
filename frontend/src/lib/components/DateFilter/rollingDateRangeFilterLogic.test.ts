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

    describe('onChange debouncing', () => {
        it('coalesces rapid counter clicks into a single onChange call', async () => {
            const onChange = jest.fn()
            logic = rollingDateRangeFilterLogic({ onChange, pageKey: 'debounce-coalesce' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.increaseCounter()
                logic.actions.increaseCounter()
                logic.actions.increaseCounter()
                logic.actions.increaseCounter()
            }).toFinishAllListeners()

            // Earlier breakpoints get cancelled, so onChange is only called once with the final value
            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange).toHaveBeenLastCalledWith('-7d')
        })

        it('fires onChange immediately when the date option changes', () => {
            const onChange = jest.fn()
            logic = rollingDateRangeFilterLogic({ onChange, pageKey: 'debounce-immediate' })
            logic.mount()

            logic.actions.setDateOption('weeks')
            expect(onChange).toHaveBeenCalledTimes(1)
            expect(onChange).toHaveBeenLastCalledWith('-3w')
        })
    })
})
