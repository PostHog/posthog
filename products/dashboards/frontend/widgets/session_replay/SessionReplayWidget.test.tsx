import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { render, screen, cleanup } from '@testing-library/react'

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

    it('shows capped total in footer when more recordings exist than the count cap', () => {
        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 1 }}
                loading={false}
                result={{
                    results: [recording],
                    hasMore: true,
                    limit: 1,
                    totalCount: 25,
                    totalCountCapped: true,
                }}
            />
        )

        expect(screen.getByText('1 of 25+ recordings')).toBeInTheDocument()
    })

    it('shows lower-bound footer when hasMore and total count was not fetched', () => {
        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 1 }}
                loading={false}
                result={{ results: [recording], hasMore: true, limit: 1 }}
            />
        )

        expect(screen.getByText('1+ recording')).toBeInTheDocument()
    })

    it('shows exact total in footer when hasMore and total is known', () => {
        render(
            <SessionReplayWidget
                tileId={1}
                config={{ limit: 1 }}
                loading={false}
                result={{
                    results: [recording],
                    hasMore: true,
                    limit: 1,
                    totalCount: 4,
                    totalCountCapped: false,
                }}
            />
        )

        expect(screen.getByText('1 of 4 recordings')).toBeInTheDocument()
    })

    it('renders an empty state when there are no recordings', () => {
        const { container } = render(
            <SessionReplayWidget tileId={1} config={{ limit: 10 }} loading={false} result={{ results: [] }} />
        )

        expect(container.querySelector('[data-attr="session-replay-widget-empty-state"]')).toBeInTheDocument()
        expect(screen.getByText('No recordings yet')).toBeInTheDocument()
    })
})
