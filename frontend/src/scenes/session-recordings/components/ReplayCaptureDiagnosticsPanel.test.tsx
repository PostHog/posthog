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
                sessionEventPropertiesLoading: true,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Loading capture diagnostics…')).toBeInTheDocument()
        })

        it('renders diagnosis when properties are loaded', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: { $recording_status: 'disabled' },
                sessionEventPropertiesLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Session recording was disabled for this session')).toBeInTheDocument()
        })

        it('renders nothing when properties are null after loading', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: null,
                sessionEventPropertiesLoading: false,
            })

            const { container } = render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(container.innerHTML).toBe('')
        })

        it('renders sampled in as unknown from loaded properties', () => {
            mockedUseValues.mockReturnValue({
                sessionEventProperties: { $recording_status: 'sampled' },
                sessionEventPropertiesLoading: false,
            })

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-789" />)

            expect(screen.getByText('Unable to determine why this recording is missing')).toBeInTheDocument()
        })
    })
})
