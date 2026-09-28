import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import {
    DEFAULT_RECORDING_FILTERS,
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

describe('SessionRecordingsPlaylistTroubleshooting', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>
    let olderRecordingStartTime: string | null = null
    const olderRecording = (): Record<string, any> => ({
        id: 'older-recording',
        start_time: olderRecordingStartTime,
        viewed: false,
        viewers: [],
    })

    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: 'troubleshooting-test',
        updateSearchParams: false,
    }

    beforeEach(() => {
        useMocks({
            get: {
                // Empty in the default 3-day range, so only a wider probe finds anything.
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const dateFrom = new URL(request.url).searchParams.get('date_from')
                    return [
                        200,
                        {
                            results: dateFrom === '-3d' || !olderRecordingStartTime ? [] : [olderRecording()],
                            has_next: false,
                        },
                    ]
                },
                '/api/environments/:team_id/session_recordings/properties': { results: [] },
            },
        })
        initKeaTests()
        logic = sessionRecordingsPlaylistLogic(logicProps)
        logic.mount()
        playerSettingsLogic.mount()
    })

    afterEach(() => {
        cleanup()
        playerSettingsLogic.actions.setHideViewedRecordings(false)
        playerSettingsLogic.unmount()
        olderRecordingStartTime = null
        logic.unmount()
        localStorage.clear()
    })

    function renderTroubleshooting(props: SessionRecordingPlaylistLogicProps = logicProps): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={props}>
                    <SessionRecordingsPlaylistTroubleshooting />
                </BindLogic>
            </Provider>
        )
    }

    it.each([
        ['no filters are applied', false, 'No recordings found'],
        ['filters are applied', true, 'No recordings match your filters'],
    ])('names the cause in the heading when %s, and always keeps the capture hints', (_, withFilters, heading) => {
        if (withFilters) {
            logic.actions.setFilters({ date_from: '-30d' })
        }

        renderTroubleshooting()

        expect(screen.getByText(heading)).toBeInTheDocument()
        // Filters being the likely cause does not rule out capture problems, so the hints stay.
        expect(screen.getByText('An ad blocker might be preventing recordings')).toBeInTheDocument()
        expect(screen.getByText('Recordings might be outside the retention period')).toBeInTheDocument()
    })

    it('offers to clear filters only when the user applied them', () => {
        renderTroubleshooting()
        expect(screen.queryByTestId('replay-empty-state-troubleshooting-clear-filters')).not.toBeInTheDocument()

        cleanup()
        logic.actions.setFilters({ date_from: '-30d' })
        renderTroubleshooting()

        expect(screen.getByText('Clear filters')).toBeInTheDocument()
    })

    it('does not offer to clear filters the caller owns, which resetFilters would drop', () => {
        const scopedProps: SessionRecordingPlaylistLogicProps = {
            logicKey: 'troubleshooting-scoped-test',
            updateSearchParams: false,
            filters: { ...DEFAULT_RECORDING_FILTERS, date_from: '-30d' },
        }
        const scopedLogic = sessionRecordingsPlaylistLogic(scopedProps)
        scopedLogic.mount()

        renderTroubleshooting(scopedProps)

        expect(scopedLogic.values.totalFiltersCount).toBeGreaterThan(0)
        expect(screen.queryByTestId('replay-empty-state-troubleshooting-clear-filters')).not.toBeInTheDocument()

        scopedLogic.unmount()
    })

    it('offers to show hidden recordings when the setting is on, even with a zero client count', () => {
        playerSettingsLogic.actions.setHideViewedRecordings('current-user')

        renderTroubleshooting()

        // Hiding is server-side, so the count is 0: the countless label proves the setting drives it.
        expect(logic.values.hiddenRecordingsCount).toBe(0)
        expect(screen.getByTestId('replay-empty-state-troubleshooting-show-hidden-recordings')).toHaveTextContent(
            /^Show hidden recordings$/
        )
    })

    it('says the project is waiting for its first recording, without the capture guesses', () => {
        const setupLogic = productSetupStatusLogic({ productKey: ProductKey.SESSION_REPLAY })
        setupLogic.mount()
        setupLogic.actions.applyDetectedStatus('waiting-for-data', teamLogic.values.currentTeamId)

        renderTroubleshooting()

        expect(screen.getByText('Waiting for the first recording')).toBeInTheDocument()
        expect(screen.queryByText('Recordings might be outside the retention period')).not.toBeInTheDocument()
        expect(screen.queryByText('Search over the last 30 days')).not.toBeInTheDocument()
    })

    it('names older recordings when the default range is empty, and widens the range to include them', async () => {
        olderRecordingStartTime = dayjs().subtract(5, 'day').toISOString()
        logic.actions.loadSessionRecordings()

        await waitFor(() => expect(logic.values.olderRecordingsProbe).not.toBeNull())
        renderTroubleshooting()

        expect(screen.getByText('No recordings in the last 3 days')).toBeInTheDocument()
        expect(screen.getByText('The newest recording started 5 days ago.')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Show older recordings'))
        await waitFor(() => expect(logic.values.filters.date_from).toBe('-30d'))
    })
})
