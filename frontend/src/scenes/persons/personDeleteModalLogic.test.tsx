import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { personDeleteModalLogic } from './personDeleteModalLogic'

const PERSON: PersonType = { id: '123', distinct_ids: ['abc'], properties: {} }

describe('personDeleteModalLogic', () => {
    let logic: ReturnType<typeof personDeleteModalLogic.build>
    let releaseDelete: () => void

    beforeEach(() => {
        initKeaTests()
        jest.spyOn(api, 'delete').mockImplementation(
            () =>
                new Promise((resolve) => {
                    releaseDelete = () => resolve(null)
                })
        )
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        jest.spyOn(lemonToast, 'success').mockImplementation(() => undefined as any)
        logic = personDeleteModalLogic()
        logic.mount()
    })

    afterEach(() => {
        if (logic.isMounted()) {
            logic.unmount()
        }
        jest.restoreAllMocks()
    })

    it('confirms the delete and refreshes the list when the surface holding the modal unmounts mid-request', async () => {
        const refreshList = jest.fn()
        logic.actions.showPersonDeleteModal(PERSON, refreshList)
        logic.actions.deletePerson(PERSON, false, false)

        logic.unmount()
        releaseDelete()
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(lemonToast.success).toHaveBeenCalled()
        expect(refreshList).toHaveBeenCalledWith(PERSON, false)
        expect(posthog.captureException).not.toHaveBeenCalled()
    })
})
