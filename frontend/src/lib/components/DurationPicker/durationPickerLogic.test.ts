import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { durationPickerLogic } from './durationPickerLogic'

describe('durationFilterLogic', () => {
    let logic: ReturnType<typeof durationPickerLogic.build>
    let filterValue = 0

    describe('core assumptions', () => {
        beforeEach(() => {
            initKeaTests()
            logic = durationPickerLogic({
                initialValue: 120,
                onChange: (value) => {
                    filterValue = value
                },
                key: 'heyheyhey',
            })
            logic.mount()
        })
        it('initial values are set', async () => {
            await expectLogic(logic).toMatchValues({
                timeValue: 2,
                unit: 'minutes',
            })
        })

        it('setTimeValue changes the value', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTimeValue(4)
            })
                .toMatchValues({ timeValue: 4, unit: 'minutes' })
                .toFinishListeners()

            expect(filterValue).toEqual(4 * 60)
        })

        it('setTimeValue to null is handled', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTimeValue(null)
            })
                .toMatchValues({ timeValue: null, unit: 'minutes' })
                .toFinishListeners()

            expect(filterValue).toEqual(0)
        })

        it('setUnit changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setUnit('seconds')
            }).toMatchValues({ timeValue: 2, unit: 'seconds' })

            expect(filterValue).toEqual(2)

            await expectLogic(logic, () => {
                logic.actions.setUnit('hours')
            }).toMatchValues({ timeValue: 2, unit: 'hours' })

            expect(filterValue).toEqual(7200)
        })
    })
    describe('no initial value', () => {
        beforeEach(() => {
            initKeaTests()
            logic = durationPickerLogic({
                onChange: (value) => {
                    filterValue = value
                },
                key: 'heyheyhey',
            })
            logic.mount()
        })

        it('initial values are set', async () => {
            await expectLogic(logic).toMatchValues({
                timeValue: null,
                unit: 'minutes',
            })
        })

        it('values can be updated', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTimeValue(2)
            }).toMatchValues({ timeValue: 2, unit: 'minutes' })

            expect(filterValue).toEqual(120)
        })
    })
})
