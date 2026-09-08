import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AssigneeMultiSelect } from './AssigneeMultiSelect'
import { assigneeSelectLogic } from './assigneeSelectLogic'

describe('AssigneeMultiSelect', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/organizations/:organization_id/members/': () => [200, { results: [] }],
                '/api/organizations/:organization_id/roles/': () => [200, { results: [] }],
            },
        })
        initKeaTests()
        // The ticket list keeps this logic mounted through its assignee cells, so the search
        // outlives one picker.
        assigneeSelectLogic.mount()
    })

    afterEach(() => {
        cleanup()
        assigneeSelectLogic.unmount()
    })

    // Regression: a keyboard activation of the X reaches the button without the pointer press
    // that dismisses the dropdown, so the close never ran and never cleared the search. The
    // query stayed set for the next picker that opened, and for the org member list.
    it('clears the shared search when the filter is removed from the keyboard', async () => {
        render(
            <Provider>
                <AssigneeMultiSelect value={[]} onChange={jest.fn()} onRemove={jest.fn()} defaultOpen />
            </Provider>
        )

        await userEvent.type(screen.getByPlaceholderText('Search'), 'ada')
        expect(assigneeSelectLogic.values.search).toBe('ada')

        screen.getByLabelText('Remove filter').focus()
        await userEvent.keyboard('{Enter}')

        expect(assigneeSelectLogic.values.search).toBe('')
    })
})
