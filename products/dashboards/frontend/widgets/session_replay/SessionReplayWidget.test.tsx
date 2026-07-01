import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import api from 'lib/api'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { SessionReplayWidget } from './SessionReplayWidget'

jest.mock('scenes/session-recordings/playlist/SessionRecordingPreview', () => ({
    SessionRecordingPreview: ({ recording }: { recording: { id: string } }): JSX.Element => (
        <div data-attr="session-recording-preview">{recording.id}</div>
    ),
    SessionRecordingPreviewSkeleton: (): JSX.Element => <div data-attr="session-recording-preview-skeleton" />,
}))

describe('SessionReplayWidget', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, session_recording_opt_in: true })
        teamLogic.mount()
    })

    const recording = {
        id: 'recording-1',
        viewed: false,
        viewers: [],
        recording_duration: 120,
        start_time: '2026-05-26T08:00:00.000Z',
        end_time: '2026-05-26T08:02:00.000Z',
        snapshot_source: 'web' as const,
    }

    it('renders recording rows from the widget result payload', () => {
        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{
                    results: [recording],
                    hasMore: false,
                    limit: 10,
                    totalCount: 1,
                    totalCountCapped: false,
                }}
            />
        )

        expect(screen.getByText('recording-1')).toBeInTheDocument()
        expect(screen.getByText('1 of 1 recording')).toBeInTheDocument()
    })

    it('renders an empty state when there are no recordings', () => {
        const { container } = render(
            <SessionReplayWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [] }} />
        )

        expect(container.querySelector('[data-attr="session-replay-widget-empty-state"]')).toBeInTheDocument()
        expect(screen.getByText('No recordings yet')).toBeInTheDocument()
        expect(screen.getByText('No session recordings matched your filters.')).toBeInTheDocument()
    })

    const matchingEventsQuery = {
        kind: 'RecordingsQuery',
        properties: [{ type: 'event', key: '$current_url', operator: 'icontains', value: ['pricing'] }],
        date_from: '-7d',
        filter_test_accounts: true,
    }

    it('opens the player without highlights when the result carries no matching events query', async () => {
        const getMatchingEvents = jest.spyOn(api.recordings, 'getMatchingEvents')
        sessionPlayerModalLogic.mount()

        render(
            <SessionReplayWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [recording] }} />
        )

        fireEvent.click(screen.getByText('recording-1'))

        await waitFor(() =>
            expect(sessionPlayerModalLogic.values.activeSessionRecording).toEqual({ id: 'recording-1' })
        )
        expect(getMatchingEvents).not.toHaveBeenCalled()
    })

    it('fetches matching events for the clicked session and opens the player with highlights', async () => {
        const events = [{ uuid: 'event-1', timestamp: '2026-05-26T08:00:30.000Z' }]
        const getMatchingEvents = jest.spyOn(api.recordings, 'getMatchingEvents').mockResolvedValue({ results: events })
        sessionPlayerModalLogic.mount()

        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{ results: [recording], matchingEventsQuery }}
            />
        )

        fireEvent.click(screen.getByText('recording-1'))

        await waitFor(() => expect(getMatchingEvents).toHaveBeenCalledTimes(1))
        // The clicked session id is layered onto the query the backend supplied.
        expect(getMatchingEvents.mock.calls[0][0]).toContain('session_ids')
        expect(getMatchingEvents.mock.calls[0][0]).toContain('recording-1')
        expect(sessionPlayerModalLogic.values.activeSessionRecording).toEqual({
            id: 'recording-1',
            matching_events: [{ session_id: 'recording-1', events }],
        })
    })

    it('falls back to opening without highlights and captures the error when the fetch fails', async () => {
        const error = new Error('boom')
        jest.spyOn(api.recordings, 'getMatchingEvents').mockRejectedValue(error)
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        sessionPlayerModalLogic.mount()

        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{ results: [recording], matchingEventsQuery }}
            />
        )

        fireEvent.click(screen.getByText('recording-1'))

        await waitFor(() =>
            expect(sessionPlayerModalLogic.values.activeSessionRecording).toEqual({ id: 'recording-1' })
        )
        // A broken query must not degrade silently.
        expect(captureException).toHaveBeenCalledWith(error, expect.objectContaining({ feature: expect.any(String) }))
    })

    it('shows a loading affordance on the row while matching events are being fetched', async () => {
        let resolveFetch: (value: { results: { uuid: string; timestamp: string }[] }) => void = () => {}
        jest.spyOn(api.recordings, 'getMatchingEvents').mockReturnValue(
            new Promise((resolve) => {
                resolveFetch = resolve
            })
        )
        sessionPlayerModalLogic.mount()

        const { container } = render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 10 }}
                loading={false}
                result={{ results: [recording], matchingEventsQuery }}
            />
        )

        fireEvent.click(screen.getByText('recording-1'))

        await waitFor(() => expect(container.querySelector('[aria-busy="true"]')).toBeInTheDocument())

        resolveFetch({ results: [] })

        await waitFor(() => expect(container.querySelector('[aria-busy="true"]')).not.toBeInTheDocument())
    })
})
