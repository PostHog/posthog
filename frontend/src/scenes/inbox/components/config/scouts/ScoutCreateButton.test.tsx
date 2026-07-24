import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SCOUT_AUTHOR_PROMPT } from '../../../utils/scoutRunsWindow'
import { ScoutCreateButton } from './ScoutCreateButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

jest.mock('./ScoutCreateModal', () => ({
    ScoutCreateModal: () => <div>Manual scout form</div>,
}))

describe('ScoutCreateButton', () => {
    let createdTaskDescriptions: string[]

    beforeEach(() => {
        createdTaskDescriptions = []
        useMocks({
            get: {
                '/api/projects/:team/signals/scout/configs/': [],
                '/api/projects/:team/signals/scout/metadata/current/': {
                    enrolled: true,
                    banner_message: null,
                    limits: {
                        max_runs_per_tick: 1,
                        max_runs_per_day: null,
                        runs_today: 0,
                        runs_remaining_today: null,
                    },
                },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
            },
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    const body = (await request.json()) as { description: string }
                    createdTaskDescriptions.push(body.description)
                    return [201, { id: 'task-1' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('starts AI authoring from the main action', async () => {
        const { getByText, queryByText } = render(<ScoutCreateButton />)

        fireEvent.click(getByText('Create scout with AI'))

        await waitFor(() => expect(createdTaskDescriptions).toEqual([SCOUT_AUTHOR_PROMPT]))
        expect(queryByText('Manual scout form')).toBeNull()
    })

    it('opens the manual form from the alternative-action menu', async () => {
        const { findByText, getByLabelText } = render(<ScoutCreateButton />)

        fireEvent.click(getByLabelText('Alternative ways to create a scout'))
        fireEvent.click(await findByText('Create manually'))

        expect(await findByText('Manual scout form')).toBeTruthy()
        expect(createdTaskDescriptions).toEqual([])
    })
})
