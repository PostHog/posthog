import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic, Provider } from 'kea'

import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { Playlist, PlaylistProps } from './Playlist'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'

jest.mock('scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed', () => ({
    RecordingsUniversalFiltersEmbedButton: () => <div data-attr="mock-filters-embed-button" />,
}))

// jsdom has no layout, so the real virtualizer measures a zero-height list and renders no rows
jest.mock('@tanstack/react-virtual', () => ({
    useVirtualizer: ({ count, getItemKey }: { count: number; getItemKey: (index: number) => string }) => ({
        isScrolling: false,
        getTotalSize: () => count * 56,
        measureElement: () => {},
        getVirtualItems: () =>
            Array.from({ length: count }, (_, index) => ({ index, key: getItemKey(index), start: index * 56 })),
    }),
}))

jest.mock('scenes/notebooks/AddToNotebook/DraggableToNotebook', () => ({
    DraggableToNotebook: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

jest.mock('scenes/session-recordings/playlist/SessionRecordingsPlaylistSettings', () => ({
    SessionRecordingsPlaylistTopSettings: () => <div data-attr="mock-top-settings" />,
}))

jest.mock('scenes/session-recordings/playlist/SessionRecordingPreview', () => ({
    SessionRecordingPreview: ({ recording }: { recording: { id: string } }) => (
        <div data-attr={`mock-recording-preview-${recording.id}`} />
    ),
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
                '/api/environments/:team_id/session_recordings': {
                    results: [
                        { id: 'r1', viewed: false, recording_duration: 10, start_time: '2024-01-01T00:00:00Z' },
                        { id: 'r2', viewed: false, recording_duration: 10, start_time: '2024-01-01T00:00:00Z' },
                    ],
                    has_next: false,
                },
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
        useMocks({ get: { '/api/environments/:team_id/session_recordings': { results: [], has_next: false } } })
        logic.actions.loadAllRecordings()
        renderPlaylist({ listEmptyState: <div data-attr="caller-empty-state" /> })

        await waitFor(() => {
            expect(logic.values.sessionRecordingsResponseLoading).toBe(false)
        })

        expect(screen.getByTestId('caller-empty-state')).toBeInTheDocument()
        expect(screen.queryByTestId('mock-troubleshooting')).not.toBeInTheDocument()
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

    it('plays or pauses the player when the user clicks the recording that is already open', async () => {
        logic.actions.setSelectedRecordingId('r1')
        const playerLogic = sessionRecordingPlayerLogic({
            playerKey: logicProps.logicKey,
            sessionRecordingId: 'r1',
        })
        playerLogic.mount()
        const togglePlayPause = jest.spyOn(playerLogic.actions, 'togglePlayPause')

        renderPlaylist({ logicKey: logicProps.logicKey })

        await userEvent.click(await screen.findByTestId('mock-recording-preview-r1'))
        expect(togglePlayPause).toHaveBeenCalledTimes(1)
        expect(logic.values.activeSessionRecordingId).toEqual('r1')

        await userEvent.click(screen.getByTestId('mock-recording-preview-r2'))
        expect(togglePlayPause).toHaveBeenCalledTimes(1)
        expect(logic.values.activeSessionRecordingId).toEqual('r2')

        playerLogic.unmount()
    })
})
