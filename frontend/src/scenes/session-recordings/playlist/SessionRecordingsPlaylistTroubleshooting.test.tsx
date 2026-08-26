import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { playerSettingsLogic } from '../player/playerSettingsLogic'
import { sessionRecordingsPlaylistLogic } from './sessionRecordingsPlaylistLogic'
import { SessionRecordingsPlaylistTroubleshooting } from './SessionRecordingsPlaylistTroubleshooting'

describe('SessionRecordingsPlaylistTroubleshooting', () => {
    let logic: ReturnType<typeof sessionRecordingsPlaylistLogic.build>

    const logicProps = { logicKey: 'troubleshooting-test', updateSearchParams: false }

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

    function renderTroubleshooting(): ReturnType<typeof render> {
        return render(
            <Provider>
                <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
                    <SessionRecordingsPlaylistTroubleshooting />
                </BindLogic>
            </Provider>
        )
    }

    it('blames capture problems only when no filters are applied', () => {
        renderTroubleshooting()

        expect(screen.getByText('No recordings found')).toBeInTheDocument()
        expect(screen.getByText('An ad blocker might be preventing recordings')).toBeInTheDocument()
    })

    it('points at the filters instead of capture problems when filters are applied', () => {
        logic.actions.setFilters({ date_from: '-30d' })

        renderTroubleshooting()

        expect(screen.getByText('No recordings match your filters')).toBeInTheDocument()
        expect(screen.getByText('Clear filters')).toBeInTheDocument()
        expect(screen.queryByText('An ad blocker might be preventing recordings')).not.toBeInTheDocument()
    })

    it('offers to show hidden recordings when the setting is on, even with a zero client count', () => {
        // Recordings are hidden server-side, so the client count is 0. The escape hatch must
        // still appear, gated on the setting rather than the count.
        playerSettingsLogic.actions.setHideViewedRecordings('current-user')

        renderTroubleshooting()

        expect(logic.values.hiddenRecordingsCount).toBe(0)
        expect(screen.getByTestId('replay-empty-state-troubleshooting-show-hidden-recordings')).toBeInTheDocument()
    })
})
