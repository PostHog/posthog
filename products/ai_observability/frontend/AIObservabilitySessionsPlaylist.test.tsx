import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AIObservabilitySessionsPlaylist } from './AIObservabilitySessionsPlaylist'

// TraceTimeline reaches the current team at module scope, which throws before initKeaTests can
// set the app context, and the detail panel imports it.
jest.mock('./AIObservabilitySessionScene', () => ({
    SessionDetailPanel: () => null,
}))

describe('AIObservabilitySessionsPlaylist', () => {
    let queryCalls: number

    beforeEach(() => {
        queryCalls = 0
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => {
                    queryCalls += 1
                    return [500, { type: 'server_error' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('offers a retry instead of the empty state when the sessions query fails', async () => {
        render(
            <Provider>
                <AIObservabilitySessionsPlaylist />
            </Provider>
        )

        expect(await screen.findByText('Could not load sessions')).toBeInTheDocument()
        expect(screen.queryByText('No sessions yet')).not.toBeInTheDocument()
        expect(screen.queryByText('Traces are not grouped into sessions')).not.toBeInTheDocument()

        // Asserting the button exists would still pass with the retry wired to nothing.
        const callsBeforeRetry = queryCalls
        await userEvent.click(await screen.findByText('Try again'))
        await waitFor(() => expect(queryCalls).toBeGreaterThan(callsBeforeRetry))
    })
})
