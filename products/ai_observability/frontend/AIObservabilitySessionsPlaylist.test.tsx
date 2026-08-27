import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AIObservabilitySessionsPlaylist } from './AIObservabilitySessionsPlaylist'

// The detail panel reads the current team at import time, before a test can set the app context.
jest.mock('./AIObservabilitySessionScene', () => ({
    SessionDetailPanel: () => null,
}))

describe('AIObservabilitySessionsPlaylist', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [500, { type: 'server_error' }],
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
        expect(screen.getByText('Retry')).toBeInTheDocument()
        expect(screen.queryByText('No sessions yet')).not.toBeInTheDocument()
        expect(screen.queryByText('Traces are not grouped into sessions')).not.toBeInTheDocument()
    })
})
