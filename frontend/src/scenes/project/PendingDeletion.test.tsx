/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_PROJECT } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, within } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import { projectLogic } from 'scenes/projectLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ProjectPendingDeletion } from './PendingDeletion'

describe('ProjectPendingDeletion', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const renderScene = async (deletionScheduledAt: string): Promise<HTMLElement> => {
        useMocks({
            get: {
                '/api/projects/@current': () => [
                    200,
                    {
                        ...MOCK_DEFAULT_PROJECT,
                        is_pending_deletion: true,
                        deletion_scheduled_at: deletionScheduledAt,
                    },
                ],
            },
        })
        projectLogic.mount()
        await expectLogic(projectLogic, () => projectLogic.actions.loadCurrentProject()).toFinishAllListeners()
        const { container } = render(
            <Provider>
                <ProjectPendingDeletion />
            </Provider>
        )
        return container
    }

    // A project that never ingested an event used to be scheduled for deletion at the current
    // instant, so the only escape the lockout screen offered could only ever return an error.
    it('offers the cancel button while the deletion is still scheduled', async () => {
        const container = await renderScene(dayjs().add(48, 'hours').toISOString())

        expect(within(container).getByText('Cancel project deletion')).toBeInTheDocument()
    })

    it('replaces the cancel button with an explanation once the deletion has started', async () => {
        const container = await renderScene(dayjs().subtract(1, 'minute').toISOString())

        expect(within(container).queryByText('Cancel project deletion')).not.toBeInTheDocument()
        expect(
            within(container).getByText('Deletion of this project has started, so it can no longer be canceled.')
        ).toBeInTheDocument()
    })
})
