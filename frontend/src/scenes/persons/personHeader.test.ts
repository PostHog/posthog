import { BuiltLogic, kea } from 'kea'

import { personHeaderLogicType } from './personHeader.testType'

import { expectLogic, initKeaTestLogic } from '~/test/kea-test-utils'
import { PersonType } from '~/types'

const personHeaderLogic = kea<personHeaderLogicType>({
    reducers: ({ props }) => ({
        withIcon: [props.withIcon || false],
    }),
})

describe('the person header', () => {
    let logic: BuiltLogic<personHeaderLogicType>

    describe('with no props', () => {
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: {},
            onLogic: (l) => (logic = l),
        })
        it('has expected defaults', () => {
            expectLogic(logic).toMatchValues({ withIcon: false })
        })
    })

    describe('withIcon props', () => {
        initKeaTestLogic({
            logic: personHeaderLogic,
            props: { withIcon: true },
            onLogic: (l) => (logic = l),
        })

        it('can set whether to show an icon from props', () => {
            expectLogic(logic).toMatchValues({ withIcon: true })
        })
    })

    it.todo('identified with name')
    it.todo('identified with email')
    it.todo('identified with neither email nor name')
    describe('with unidentified person', () => {
        const person: Partial<PersonType> | null = {}

        initKeaTestLogic({
            logic: personHeaderLogic,
            props: { person },
            onLogic: (l) => (logic = l),
        })

        it('shows unidentified people with a hash', () => {
            expectLogic(logic).toMatchValues({
                displayName: 'Unidentified',
            })
        })
    })
})
