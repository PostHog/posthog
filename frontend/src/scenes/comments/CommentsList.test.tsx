import '@testing-library/jest-dom'

import { act, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { CommentsList } from './CommentsList'
import { commentsLogic } from './commentsLogic'

const PROPS = { scope: ActivityScope.TICKET, item_id: 'ticket-1' }

describe('CommentsList', () => {
    let logic: ReturnType<typeof commentsLogic.build>
    let answerFirstLoad: () => void = () => {}

    beforeEach(() => {
        initKeaTests()

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

        logic = commentsLogic(PROPS)
        logic.mount()
    })

    // The background poll shares one loading flag with the first fetch, so a skeleton keyed off
    // that flag takes the empty state off screen every time the poll runs.
    it('shows the empty state once loaded and keeps it through a background refresh', async () => {
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

        // Let the refresh land, so its request doesn't settle after teardown
        await waitFor(() => expect(logic.values.commentsLoading).toBe(false))
    })
})
