import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { expectLogic } from 'kea-test-utils'
import { initKeaTestLogic } from '~/test/init'
import { personsLogic } from './personsLogic'
import { router } from 'kea-router'
import { PropertyOperator } from '~/types'

jest.mock('lib/api')

describe('personsLogic', () => {
    let logic: ReturnType<typeof personsLogic.build>

    mockAPI(async (url) => {
        const { pathname, searchParams } = url
        if (`api/person/` === pathname && searchParams == { properties: [{ key: 'email', operator: 'is_set' }] }) {
            return { result: ['result from api'] }
        }
        return defaultAPIMocks(url)
    })

    describe('syncs with insightLogic', () => {
        initKeaTestLogic({
            logic: personsLogic,
            props: { syncWithUrl: true },
            onLogic: (l) => (logic = l),
        })

        it('setAllFilters properties works', async () => {
            router.actions.push('/persons')
            await expectLogic(logic, () => {
                logic.actions.setListFilters({
                    properties: [{ key: 'email', operator: PropertyOperator.IsSet }],
                })
                logic.actions.loadPersons()
            })
                .toMatchValues(logic, {
                    listFilters: { properties: [{ key: 'email', operator: 'is_set' }] },
                })
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: { properties: [{ key: 'email', operator: 'is_set' }] } })
        })
        it('properties from url works', async () => {
            router.actions.push('/persons', { properties: [{ key: 'email', operator: 'is_set' }] })
            await expectLogic(logic, () => {}).toMatchValues(logic, {
                listFilters: { properties: [{ key: 'email', operator: 'is_set' }] },
            })

            // Expect a clean url (no ?properties={})
            await expectLogic(logic, () => {
                logic.actions.setListFilters({
                    properties: [],
                })
                logic.actions.loadPersons()
            })
                .toDispatchActions(router, ['replace', 'locationChanged'])
                .toMatchValues(router, { searchParams: {} })
        })
    })
})
