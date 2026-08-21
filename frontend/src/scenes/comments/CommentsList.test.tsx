import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { CommentsList } from './CommentsList'
import { commentsLogic } from './commentsLogic'

const PROPS = { scope: ActivityScope.TICKET, item_id: 'ticket-1' }

afterEach(cleanup)

describe('CommentsList', () => {
    // Loading, empty, and loaded are three different screens, and a thread that has already answered
    // is never the first of them again. Branching the skeleton on `commentsLoading` broke that: the
    // ticket page polls `refreshComments` every 20 seconds, that shares the loader's flag with the
    // first fetch, so an open panel dropped its empty state and jumped the composer up the panel
    // every 20 seconds while someone was typing into it.
    it('shows the empty state once loaded and keeps it through a background refresh', async () => {
        initKeaTests()

        let answerFirstLoad: () => void = () => {}
        const firstLoadReached = new Promise<void>((resolve) => {
            answerFirstLoad = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/comments': async () => {
                    await firstLoadReached
                    return [200, { results: [] }]
                },
                '/api/organizations/@current/members/': { results: [] },
            },
        })

        const logic = commentsLogic(PROPS)
        logic.mount()

        render(
            <Provider>
                <CommentsList {...PROPS} />
            </Provider>
        )

        // Nothing has answered yet, so there is no empty thread to claim
        expect(screen.queryByText('Start the discussion!')).not.toBeInTheDocument()

        await act(async () => {
            answerFirstLoad()
        })
        await waitFor(() => expect(screen.getByText('Start the discussion!')).toBeInTheDocument())

        act(() => {
            logic.actions.refreshComments()
        })
        expect(logic.values.commentsLoading).toBe(true)
        expect(screen.getByText('Start the discussion!')).toBeInTheDocument()
    })
})
