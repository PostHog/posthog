import { api } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { addPersonToCohortModalLogic } from './addPersonToCohortModalLogic'

describe('addPersonToCohortModalLogic', () => {
    let logic: ReturnType<typeof addPersonToCohortModalLogic.build>

    beforeEach(() => {
        jest.spyOn(api, 'get')
        initKeaTests()
        logic = addPersonToCohortModalLogic({ id: 1 })
        logic.mount()
    })

    it('keeps the display name so it can be shown in the selected list, and forgets it on remove', async () => {
        await expectLogic(logic, () => {
            logic.actions.addPerson('person-1', 'Jane Doe')
        }).toMatchValues({
            personsToAddToCohort: { 'person-1': 'Jane Doe' },
        })

        await expectLogic(logic, () => {
            logic.actions.removePerson('person-1')
        }).toMatchValues({
            personsToAddToCohort: {},
        })
    })
})
