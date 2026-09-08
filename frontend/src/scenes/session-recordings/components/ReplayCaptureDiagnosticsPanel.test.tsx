import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { ReplayCaptureDiagnosticsPanel } from './ReplayCaptureDiagnosticsPanel'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
}))

jest.mock('./replayCaptureDiagnosticsPanelLogic', () => ({
    replayCaptureDiagnosticsPanelLogic: jest.fn(),
}))

const mockedUseValues = useValues as jest.Mock

describe('ReplayCaptureDiagnosticsPanel', () => {
    describe('with eventProperties prop', () => {
        afterEach(() => {
            cleanup()
        })

        it('renders captured headline when $has_recording is true', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $has_recording: true,
                        $recording_status: 'active',
                    }}
                />
            )

            expect(screen.getByText('A recording exists for this session')).toBeInTheDocument()
        })

        it('renders ad blocked headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $sdk_debug_recording_script_not_loaded: true,
                    }}
                />
            )

            expect(
                screen.getByText('The recording script failed to load — likely blocked by an ad blocker')
            ).toBeInTheDocument()
        })

        it('renders disabled headline when remote config says replay is off', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'disabled',
                        $session_recording_remote_config: { enabled: false },
                    }}
                />
            )

            expect(screen.getByText('PostHog told the SDK not to record this session')).toBeInTheDocument()
        })

        it('renders recorder_not_started headline for a bare disabled snapshot', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'disabled',
                    }}
                />
            )

            expect(screen.getByText('The recorder was not running for this session')).toBeInTheDocument()
        })

        it('renders recorder_loading headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'lazy_loading',
                    }}
                />
            )

            expect(screen.getByText('The recorder had not finished loading yet')).toBeInTheDocument()
        })

        it('renders a status posthog-js never emits as unknown', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'sampled',
                    }}
                />
            )

            expect(screen.getByText('Unable to determine why this recording is missing')).toBeInTheDocument()
        })

        it('renders trigger pending headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $sdk_debug_replay_url_trigger_status: 'trigger_pending',
                        $sdk_debug_replay_event_trigger_status: 'trigger_disabled',
                    }}
                />
            )

            expect(screen.getByText('Recording was gated on a trigger that never fired')).toBeInTheDocument()
        })

        it('renders suggested action buttons for disabled verdict', () => {
            const { container } = render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'disabled',
                        $session_recording_remote_config: { enabled: false },
                    }}
                />
            )

            const links = container.querySelectorAll('a')
            const hrefs = Array.from(links).map((a) => a.getAttribute('href'))
            expect(hrefs.some((h) => h?.includes('project-replay'))).toBe(true)
            expect(hrefs.some((h) => h?.includes('troubleshooting'))).toBe(true)
        })

        it('renders unknown headline for empty properties', () => {
            render(<ReplayCaptureDiagnosticsPanel eventProperties={{}} />)

            expect(screen.getByText('Unable to determine why this recording is missing')).toBeInTheDocument()
        })

        it('renders reason list items', () => {
            const { container } = render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $has_recording: true,
                    }}
                />
            )

            const listItems = container.querySelectorAll('li')
            expect(listItems.length).toBeGreaterThan(0)
            const text = Array.from(listItems)
                .map((li) => li.textContent)
                .join(' ')
            expect(text).toContain('$has_recording = true')
        })

        it('renders buffering_empty headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'buffering',
                        $sdk_debug_replay_internal_buffer_length: 0,
                        $sdk_debug_replay_flushed_size: 0,
                    }}
                />
            )

            expect(screen.getByText('Recording initialized but no snapshots were produced')).toBeInTheDocument()
        })
    })

    describe('with sessionId prop', () => {
        afterEach(() => {
            cleanup()
        })

        it('shows loading state when properties are loading', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: null,
                sessionRecordingStatuses: [],
                captureDiagnosticsLoading: true,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Loading capture diagnostics…')).toBeInTheDocument()
        })

        it('renders diagnosis when properties are loaded', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: { $recording_status: 'disabled' },
                sessionRecordingStatuses: ['disabled'],
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('The recorder was not running for this session')).toBeInTheDocument()
        })

        it('re-reads a disabled latest event against the rest of the session', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: { $recording_status: 'disabled' },
                sessionRecordingStatuses: ['disabled', 'lazy_loading'],
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-456" />)

            expect(screen.getByText('The recorder had not finished loading yet')).toBeInTheDocument()
        })

        it('renders nothing when properties are null after loading', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: null,
                sessionRecordingStatuses: [],
                captureDiagnosticsLoading: false,
            })

            const { container } = render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(container.innerHTML).toBe('')
        })

        it('renders a status posthog-js never emits as unknown from loaded properties', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: { $recording_status: 'sampled' },
                sessionRecordingStatuses: ['sampled'],
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-789" />)

            expect(screen.getByText('Unable to determine why this recording is missing')).toBeInTheDocument()
        })
    })
})
