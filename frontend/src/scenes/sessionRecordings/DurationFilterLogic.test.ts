import { DurationFilterLogicType } from './DurationFilterLogicType'
import { BuiltLogic } from 'kea'
import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { PropertyOperator } from '~/types'
import { DurationFilterLogic, DurationFilterProps, TimeUnit } from './DurationFilterLogic'

jest.mock('lib/api')

describe('durationFilterLogic', () => {
    let logic: BuiltLogic<DurationFilterLogicType<DurationFilterProps, TimeUnit>>
    let filterValue = {}
    initKeaTestLogic({
        logic: DurationFilterLogic,
        props: {
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
        },
        onLogic: (l) => (logic = l),
    })

    describe('core assumptions', () => {
        it('initial values are set', async () => {
            await expectLogic(logic).toMatchValues({
                unit: TimeUnit.MINUTES,
                operator: PropertyOperator.GreaterThan,
                timeValue: 1,
                isOpen: false,
                durationString: '> 1 minute',
            })
        })

        it('setTimeValue changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTimeValue(2)
            })
                .toMatchValues({ timeValue: 2, durationString: '> 2 minutes' })
                .toFinishListeners()

            expect(filterValue).toMatchObject({
                value: 120,
                operator: PropertyOperator.GreaterThan,
            })
        })

        it('setUnit changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setUnit(TimeUnit.HOURS)
            }).toMatchValues({ unit: TimeUnit.HOURS, durationString: '> 1 hour' })

            expect(filterValue).toMatchObject({
                value: 3600,
                operator: PropertyOperator.GreaterThan,
            })
        })

        it('setUnit to seconds changes the value and updates the string', async () => {
            await expectLogic(logic, () => {
                logic.actions.setUnit(TimeUnit.SECONDS)
                logic.actions.setTimeValue(100)
            }).toMatchValues({ unit: TimeUnit.SECONDS, durationString: '> 100 seconds' })

            expect(filterValue).toMatchObject({
                value: 100,
                operator: PropertyOperator.GreaterThan,
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
