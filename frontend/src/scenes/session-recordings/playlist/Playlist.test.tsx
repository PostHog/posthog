import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Playlist } from './Playlist'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

jest.mock('scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed', () => ({
    RecordingsUniversalFiltersEmbedButton: () => <div data-attr="mock-filters-embed-button" />,
}))

jest.mock('scenes/notebooks/AddToNotebook/DraggableToNotebook', () => ({
    DraggableToNotebook: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

jest.mock('scenes/session-recordings/playlist/SessionRecordingsPlaylistSettings', () => ({
    SessionRecordingsPlaylistTopSettings: () => <div data-attr="mock-top-settings" />,
}))

jest.mock('scenes/session-recordings/playlist/SessionRecordingPreview', () => ({
    SessionRecordingPreview: () => <div data-attr="mock-recording-preview" />,
}))

jest.mock('./SessionRecordingsPlaylistTroubleshooting', () => ({
    SessionRecordingsPlaylistTroubleshooting: () => <div data-attr="mock-troubleshooting" />,
}))

describe('Playlist', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

    const logicProps = { logicKey: 'playlist-component-test', updateSearchParams: false }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': { results: [], has_next: false },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
            },
        })
        initKeaTests()
        logic = sessionRecordingsPlaylistLogic(logicProps)
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        localStorage.clear()
    })

    function renderPlaylist(): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                    <Playlist />
                </BindLogic>
            </Provider>
        )
    }

    it('does not show the selected sessions notice when no session_ids filter is set', () => {
        renderPlaylist()

        expect(screen.queryByText(/selected recording/)).not.toBeInTheDocument()
        expect(screen.queryByText('Show all')).not.toBeInTheDocument()
    })

    it('shows the selected sessions notice and clears session_ids via "Show all"', async () => {
        logic.actions.setFilters({ session_ids: ['s1', 's2'] })

        renderPlaylist()

        expect(screen.getByText('Showing 2 selected recordings')).toBeInTheDocument()

        await waitFor(() => {
            expect(logic.values.sessionRecordingsResponseLoading).toBe(false)
        })

        userEvent.click(screen.getByText('Show all'))

        await waitFor(() => {
            expect(logic.values.filters.session_ids).toBeUndefined()
        })
        expect(screen.queryByText(/selected recording/)).not.toBeInTheDocument()
    })

    it('recovers from a failed load via the error banner', async () => {
        useMocks({ get: { '/api/environments/:team_id/session_recordings': () => [500, { detail: 'boom' }] } })
        logic.actions.loadSessionRecordings()

        renderPlaylist()

        expect((await screen.findAllByText("We couldn't load recordings.")).length).toBeGreaterThan(0)

        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': { results: [], has_next: false },
            },
        })
        userEvent.click(screen.getAllByText('Try again')[0])

        // A successful reload has to clear the error, even when it legitimately finds nothing.
        await waitFor(() => {
            expect(screen.queryByText("We couldn't load recordings.")).not.toBeInTheDocument()
        })
        expect((await screen.findAllByTestId('mock-troubleshooting')).length).toBeGreaterThan(0)
    })
})
