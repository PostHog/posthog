import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Playlist, PlaylistProps } from './Playlist'
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

    function renderPlaylist(props: PlaylistProps = {}): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                    <Playlist {...props} />
                </BindLogic>
            </Provider>
        )
    }

    it('does not show the selected sessions notice when no session_ids filter is set', () => {
        renderPlaylist()

        expect(screen.queryByText(/selected recording/)).not.toBeInTheDocument()
        expect(screen.queryByText('Show all')).not.toBeInTheDocument()
    })

    it('lets the caller replace the troubleshooting panel for an empty list', async () => {
        renderPlaylist({ listEmptyState: <div data-attr="caller-empty-state" /> })

        await waitFor(() => {
            expect(logic.values.sessionRecordingsResponseLoading).toBe(false)
        })

        expect(screen.getByTestId('caller-empty-state')).toBeInTheDocument()
        expect(screen.queryByTestId('mock-troubleshooting')).not.toBeInTheDocument()
    })

    it('names the reason a list load failed and retries it', async () => {
        let attempts = 0
        useMocks({
            get: {
                '/api/environments/:team_id/session_recordings': () => {
                    attempts += 1
                    return [500, { detail: 'Query exceeded memory limits.' }]
                },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
            },
        })

        renderPlaylist()
        logic.actions.loadSessionRecordings(undefined, undefined, true)

        await waitFor(() => {
            expect(screen.getByText(/Query exceeded memory limits\./)).toBeInTheDocument()
        })

        const attemptsBeforeRetry = attempts
        // The banner renders its action twice, one copy per width; either is the same button.
        userEvent.click(screen.getAllByTestId('session-recordings-list-retry')[0])

        await waitFor(() => {
            expect(attempts).toBeGreaterThan(attemptsBeforeRetry)
        })
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
})
