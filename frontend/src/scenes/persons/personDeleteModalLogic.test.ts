import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from './personDeleteModalLogic'

const PERSON = { id: 1, uuid: 'abc-123', distinct_ids: ['a'], name: 'a' } as unknown as PersonType

describe('personDeleteModalLogic', () => {
    let logic: ReturnType<typeof personDeleteModalLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = personDeleteModalLogic()
        logic.mount()
        router.actions.push('/persons')
    })

    afterEach(resumeKeaLoadersErrors)

    it('closes the modal after a successful delete', async () => {
        useMocks({ delete: { '/api/person/:id': [202, {}] } })
        logic.actions.showPersonDeleteModal(PERSON)

        await expectLogic(logic, () => {
            logic.actions.deletePerson(PERSON, false, false)
        })
            .toDispatchActions(['deletePersonSuccess'])
            .toMatchValues({ personDeleteModal: null, deletedPersonLoading: false })
    })

    it('keeps the modal open when the delete request fails', async () => {
        silenceKeaLoadersErrors()
        useMocks({ delete: { '/api/person/:id': [500, { detail: 'nope' }] } })
        logic.actions.showPersonDeleteModal(PERSON)

        await expectLogic(logic, () => {
            logic.actions.deletePerson(PERSON, false, false)
        })
            .toDispatchActions(['deletePersonFailure'])
            .toMatchValues({ personDeleteModal: PERSON, deletedPersonLoading: false })
    })
})
