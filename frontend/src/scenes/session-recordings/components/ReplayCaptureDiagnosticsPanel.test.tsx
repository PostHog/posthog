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
                screen.getByText('The recording script failed to load, likely blocked by an ad blocker')
            ).toBeInTheDocument()
        })

        it('renders disabled headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'disabled',
                    }}
                />
            )

            expect(screen.getByText('Session recording was disabled for this session')).toBeInTheDocument()
        })

        it('renders sampled in as unknown (sampled means recording started)', () => {
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
            expect(text).toContain('PostHog has a stored recording linked to this session')
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

        it('shows loading state when diagnostics are loading', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: null,
                captureDiagnosticsLoading: true,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Loading capture diagnostics…')).toBeInTheDocument()
        })

        it('renders diagnosis when properties are loaded', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: { properties: { $recording_status: 'disabled' }, recordingExists: false },
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Session recording was disabled for this session')).toBeInTheDocument()
        })

        it('renders nothing when properties are null after loading', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: { properties: null, recordingExists: false },
                captureDiagnosticsLoading: false,
            })

            const { container } = render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(container.innerHTML).toBe('')
        })

        it('renders sampled in as unknown from loaded properties', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: { properties: { $recording_status: 'sampled' }, recordingExists: null },
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-789" />)

            expect(screen.getByText('Unable to determine why this recording is missing')).toBeInTheDocument()
        })

        it('says a recording is stored and links to it when the server found one', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: {
                    properties: { $recording_status: 'active', $sdk_debug_replay_flushed_size: 500 },
                    recordingExists: true,
                },
                captureDiagnosticsLoading: false,
            })

            const { container } = render(<ReplayCaptureDiagnosticsPanel sessionId="session-456" />)

            expect(screen.getByText('PostHog has a recording for this session')).toBeInTheDocument()
            const hrefs = Array.from(container.querySelectorAll('a')).map((a) => a.getAttribute('href'))
            expect(hrefs).toContain('/replay/session-456')
            expect(hrefs.some((h) => h?.includes('session_ids'))).toBe(true)
        })

        it('renders the stored-recording answer even when no diagnostic event was found', () => {
            mockedUseValues.mockReturnValue({
                captureDiagnostics: { properties: null, recordingExists: true },
                captureDiagnosticsLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-456" />)

            expect(screen.getByText('PostHog has a recording for this session')).toBeInTheDocument()
        })
    })
})
