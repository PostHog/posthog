import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import api from 'lib/api'

import { ReplayCaptureDiagnosticsPanel } from './ReplayCaptureDiagnosticsPanel'

jest.mock('lib/api', () => ({
    queryHogQL: jest.fn(),
}))

const mockedQueryHogQL = api.queryHogQL as jest.Mock

describe('ReplayCaptureDiagnosticsPanel', () => {
    describe('with eventProperties prop', () => {
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

        it('renders sampled out headline', () => {
            render(
                <ReplayCaptureDiagnosticsPanel
                    eventProperties={{
                        $recording_status: 'sampled',
                    }}
                />
            )

            expect(screen.getByText('This session was excluded by sampling')).toBeInTheDocument()
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

        beforeEach(() => {
            jest.clearAllMocks()
        })

        it('shows loading state initially', () => {
            mockedQueryHogQL.mockReturnValue(new Promise(() => {}))

            render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)

            expect(screen.getByText('Loading capture diagnostics…')).toBeInTheDocument()
        })

        it('renders diagnosis after fetching properties', async () => {
            mockedQueryHogQL.mockResolvedValue({
                results: [[{ $recording_status: 'disabled' }]],
            })

            await act(async () => {
                render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)
            })

            await waitFor(() => {
                expect(screen.getByText('Session recording was disabled for this session')).toBeInTheDocument()
            })
        })

        it('renders nothing when fetch returns no results', async () => {
            mockedQueryHogQL.mockResolvedValue({
                results: [],
            })

            const { container } = await act(async () => {
                return render(<ReplayCaptureDiagnosticsPanel sessionId="session-123" />)
            })

            await waitFor(() => {
                expect(screen.queryByText('Loading capture diagnostics…')).not.toBeInTheDocument()
            })
            expect(container.innerHTML).toBe('')
        })

        it('renders nothing when fetch errors', async () => {
            mockedQueryHogQL.mockRejectedValue(new Error('network error'))

            const { container } = await act(async () => {
                return render(<ReplayCaptureDiagnosticsPanel sessionId="session-456" />)
            })

            await waitFor(() => {
                expect(screen.queryByText('Loading capture diagnostics…')).not.toBeInTheDocument()
            })
            expect(container.innerHTML).toBe('')
        })

        it('parses JSON string result from HogQL', async () => {
            mockedQueryHogQL.mockResolvedValue({
                results: [[JSON.stringify({ $recording_status: 'sampled' })]],
            })

            await act(async () => {
                render(<ReplayCaptureDiagnosticsPanel sessionId="session-789" />)
            })

            await waitFor(() => {
                expect(screen.getByText('This session was excluded by sampling')).toBeInTheDocument()
            })
        })

        it('calls queryHogQL with the session ID', async () => {
            mockedQueryHogQL.mockResolvedValue({
                results: [[{ $recording_status: 'active', $sdk_debug_replay_flushed_size: 100 }]],
            })

            await act(async () => {
                render(<ReplayCaptureDiagnosticsPanel sessionId="my-session-id" />)
            })

            expect(mockedQueryHogQL).toHaveBeenCalledTimes(1)
            const query = mockedQueryHogQL.mock.calls[0][0]
            expect(query).toContain('my-session-id')
        })
    })
})
