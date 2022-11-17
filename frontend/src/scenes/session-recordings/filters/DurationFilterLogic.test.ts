import { expectLogic } from 'kea-test-utils'
import { initKeaTests } from '~/test/init'
import { PropertyOperator } from '~/types'
import { durationFilterLogic } from './durationFilterLogic'

describe('durationFilterLogic', () => {
    let logic: ReturnType<typeof durationFilterLogic.build>
    let filterValue = {}
    beforeEach(() => {
        initKeaTests()
        logic = durationFilterLogic({
            initialFilter: {
                type: 'recording',
                key: 'duration',
                value: 60,
                operator: PropertyOperator.GreaterThan,
            },
            onChange: (value) => {
                filterValue = value
            },
            pageKey: 'heyheyhey',
        })
        logic.mount()
    })

    describe('core assumptions', () => {
        it('initial values are set', async () => {
            await expectLogic(logic).toMatchValues({
                operator: PropertyOperator.GreaterThan,
                value: 60,
                isOpen: false,
                durationString: '> 1 minute',
            })
        })

        it('setValue changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setValue(120)
            })
                .toMatchValues({ value: 120, durationString: '> 2 minutes' })
                .toFinishListeners()

            expect(filterValue).toMatchObject({
                value: 120,
                operator: PropertyOperator.GreaterThan,
            })
        })

        it('setValue to null is handled', async () => {
            await expectLogic(logic, () => {
                logic.actions.setValue(null)
            })
                .toMatchValues({ value: null, durationString: '> 0 seconds' })
                .toFinishListeners()

            expect(filterValue).toMatchObject({
                value: 0,
            })
        })

        it('setOperator changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setOperator(PropertyOperator.LessThan)
            }).toMatchValues({ operator: PropertyOperator.LessThan, durationString: '< 1 minute' })

            expect(filterValue).toMatchObject({
                value: 60,
                operator: PropertyOperator.LessThan,
            })
        })

        it('setIsOpen changes the value', async () => {
            await expectLogic(logic, () => {
                logic.actions.setIsOpen(true)
            }).toMatchValues({ isOpen: true })
        })
    })
})
