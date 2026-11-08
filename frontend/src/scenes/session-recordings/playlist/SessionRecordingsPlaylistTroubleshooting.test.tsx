import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
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

    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: 'troubleshooting-test',
        updateSearchParams: false,
    }

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
        playerSettingsLogic.mount()
    })

    afterEach(() => {
        cleanup()
        playerSettingsLogic.actions.setHideViewedRecordings(false)
        playerSettingsLogic.unmount()
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

    it('offers to show recordings hidden by the activity filter, and clicking clears the duration filter', () => {
        logic.actions.loadRecordingsHiddenByActivityFilterSuccess({ count: 14, hasMore: false })

        renderTroubleshooting()

        const button = screen.getByTestId('replay-empty-state-troubleshooting-show-activity-hidden-recordings')
        expect(button).toHaveTextContent(/^Show 14 recordings shorter than 5 active seconds$/)

        fireEvent.click(button)

        expect(logic.values.filters.duration).toEqual([])
    })

    it('uses the singular for a single recording hidden by the activity filter', () => {
        logic.actions.loadRecordingsHiddenByActivityFilterSuccess({ count: 1, hasMore: false })

        renderTroubleshooting()

        expect(
            screen.getByTestId('replay-empty-state-troubleshooting-show-activity-hidden-recordings')
        ).toHaveTextContent(/^Show 1 recording shorter than 5 active seconds$/)
    })

    it('marks the count as a floor when more recordings are hidden', () => {
        logic.actions.loadRecordingsHiddenByActivityFilterSuccess({ count: 3, hasMore: true })

        renderTroubleshooting()

        expect(
            screen.getByTestId('replay-empty-state-troubleshooting-show-activity-hidden-recordings')
        ).toHaveTextContent(/^Show 3\+ recordings shorter than 5 active seconds$/)
    })

    it('does not offer the activity filter row once the default duration filter is gone', () => {
        logic.actions.loadRecordingsHiddenByActivityFilterSuccess({ count: 14, hasMore: false })
        logic.actions.setFilters({ duration: [] })

        renderTroubleshooting()

        expect(
            screen.queryByTestId('replay-empty-state-troubleshooting-show-activity-hidden-recordings')
        ).not.toBeInTheDocument()
    })

    it('does not offer the activity filter row when the probe found nothing hidden', () => {
        renderTroubleshooting()

        expect(
            screen.queryByTestId('replay-empty-state-troubleshooting-show-activity-hidden-recordings')
        ).not.toBeInTheDocument()
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
})
