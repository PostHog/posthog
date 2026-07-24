import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SCOUT_AUTHOR_PROMPT } from '../../../utils/scoutRunsWindow'
import { ScoutCreateButton } from './ScoutCreateButton'

jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

jest.mock('./ScoutCreateModal', () => ({
    ScoutCreateModal: ({ initialValues }: { initialValues?: { name?: string } }) => (
        <div>
            Manual scout form
            {initialValues?.name ? <span>{initialValues.name}</span> : null}
        </div>
    ),
}))

const mockGetAccessControlDisabledReason = getAccessControlDisabledReason as jest.MockedFunction<
    typeof getAccessControlDisabledReason
>

describe('ScoutCreateButton', () => {
    let createdTaskDescriptions: string[]

    beforeEach(() => {
        createdTaskDescriptions = []
        mockGetAccessControlDisabledReason.mockReturnValue(null)
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

    it('opens a prefilled manual form directly when configured for manual creation', async () => {
        const { findByText, getByText, queryByLabelText } = render(
            <ScoutCreateButton
                creationMode="manual"
                initialValues={{ name: 'signals-scout-daily-digest' }}
                type="secondary"
            >
                Create daily digest
            </ScoutCreateButton>
        )

        fireEvent.click(getByText('Create daily digest'))

        expect(await findByText('Manual scout form')).toBeTruthy()
        expect(await findByText('signals-scout-daily-digest')).toBeTruthy()
        expect(queryByLabelText('Alternative ways to create a scout')).toBeNull()
        expect(createdTaskDescriptions).toEqual([])
    })

    it('does not start AI authoring without skill editor access', () => {
        mockGetAccessControlDisabledReason.mockReturnValue('Requires editor access')
        const { getByText } = render(<ScoutCreateButton />)
        const createButton = getByText('Create scout with AI').closest<HTMLButtonElement>('button')

        expect(createButton?.getAttribute('aria-disabled')).toBe('true')
        fireEvent.click(createButton!)
        expect(createdTaskDescriptions).toEqual([])
    })
})
