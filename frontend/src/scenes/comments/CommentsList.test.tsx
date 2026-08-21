import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { CommentsList } from './CommentsList'
import { commentsLogic } from './commentsLogic'

const PROPS = { scope: ActivityScope.TICKET, item_id: 'ticket-1' }

const FAILING_LOAD = {
    get: {
        '/api/projects/:team_id/comments': () => [500, { detail: 'nope' }],
        '/api/organizations/@current/members/': { results: [] },
    },
}

afterEach(cleanup)

describe('CommentsList', () => {
    // Loading, empty, and loaded are three different screens, and a thread that has already answered
    // is never the first of them again. The ticket page refreshes this one every 20 seconds, and
    // every handler on the `comments` loader shares one loading flag with the first fetch.
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

        // Let the refresh land, so its request doesn't settle after teardown
        await waitFor(() => expect(logic.values.commentsLoading).toBe(false))
    })

    const mountAndRender = (): ReturnType<typeof commentsLogic.build> => {
        const logic = commentsLogic(PROPS)
        logic.mount()

        render(
            <Provider>
                <CommentsList {...PROPS} />
            </Provider>
        )

        return logic
    }

    it('shows an error state when the first load fails', async () => {
        initKeaTests()
        useMocks(FAILING_LOAD)
        const logic = mountAndRender()

        await waitFor(() => expect(screen.getByText("Couldn't load the discussion.")).toBeInTheDocument())
        // A thread nobody has posted in and a thread that never answered read the same otherwise, so
        // the reader is invited to start a discussion that may already be underway
        expect(screen.queryByText('Start the discussion!')).not.toBeInTheDocument()
        expect(logic.values.comments).toBe(null)
    })

    it('keeps the error state through a background refresh', async () => {
        initKeaTests()
        useMocks(FAILING_LOAD)
        const logic = mountAndRender()

        await waitFor(() => expect(screen.getByText("Couldn't load the discussion.")).toBeInTheDocument())

        act(() => {
            logic.actions.refreshComments()
        })
        expect(logic.values.commentsLoading).toBe(true)
        expect(screen.getByText("Couldn't load the discussion.")).toBeInTheDocument()

        await waitFor(() => expect(logic.values.commentsLoading).toBe(false))
        expect(screen.getByText("Couldn't load the discussion.")).toBeInTheDocument()
    })
})
