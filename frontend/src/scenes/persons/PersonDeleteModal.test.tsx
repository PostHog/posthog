import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { PersonDeleteModal } from './PersonDeleteModal'
import { personDeleteModalLogic } from './personDeleteModalLogic'

const PERSON: PersonType = { id: '123', distinct_ids: ['abc'], properties: {} }

describe('<PersonDeleteModal />', () => {
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
        logic = personDeleteModalLogic()
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        jest.restoreAllMocks()
    })

    // react-modal keeps the content clickable for its 250ms close animation, so a second click
    // either sent a duplicate DELETE or, once the person was cleared, threw on `person.id`.
    it('sends one delete request when the button is clicked again while the request is in flight and after it settles', async () => {
        const user = userEvent.setup()
        logic.actions.showPersonDeleteModal(PERSON)
        render(<PersonDeleteModal />)

        await user.type(screen.getByPlaceholderText('delete'), 'delete')
        const deleteButton = screen.getByText('Delete person')

        await user.click(deleteButton)
        await user.click(deleteButton)
        expect(api.delete).toHaveBeenCalledTimes(1)

        releaseDelete()
        await new Promise((resolve) => setTimeout(resolve, 0))

        await user.click(deleteButton)
        expect(api.delete).toHaveBeenCalledTimes(1)
        expect(posthog.captureException).not.toHaveBeenCalled()
    })
})
