import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RecordingExistsState, sessionRecordingInfoLogic } from './sessionRecordingInfoLogic'
import ViewRecordingButton, { recordingDisabledReason } from './ViewRecordingButton'

describe('recordingDisabledReason', () => {
    // Malformed SDK payloads can send $session_id as a non-string (dict/array/number). Such a value
    // can't address a recording; without this guard the button stays enabled and links to
    // /replay/[object Object]. See the events-query non-string $session_id fix.
    it.each([
        ['object', { bytes: { 0: 1 } }],
        ['array', [1, 2, 3]],
        ['number', 12345],
    ])('disables with "No recording for this event" when $session_id is a %s', (_label, sessionId) => {
        expect(recordingDisabledReason(sessionId as unknown as string, undefined, undefined)).toBe(
            'No recording for this event'
        )
    })

    it('does not disable for a valid string session id with a recording', () => {
        expect(recordingDisabledReason('0190-good-session', undefined, true)).toBeNull()
    })

    it('disables when the server reports no recording exists', () => {
        expect(recordingDisabledReason('0190-good-session', undefined, false)).toBe('No recording for this event')
    })

    it('prompts to set a session id when it is genuinely absent', () => {
        // Absent (not malformed) keeps the existing "no session id" guidance rather than "no recording".
        expect(recordingDisabledReason(undefined, undefined, undefined)).not.toBeNull()
        expect(typeof recordingDisabledReason(undefined, undefined, undefined)).not.toBe('string')
    })
})

describe('ViewRecordingButton recording availability', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        sessionRecordingInfoLogic.mount()
    })

    afterEach(() => cleanup())

    it.each([
        ['control', true, 'disabled', false, true],
        ['session_lookup', true, 'disabled', false, false],
        ['session_lookup', false, 'disabled', false, true],
        ['session_lookup', true, 'disabled', true, false],
    ])(
        'uses the %s variant when the session lookup returns %s',
        async (variant, exists, status, hasRecording, isDisabled) => {
            useMocks({
                post: {
                    '/api/projects/:team/session_recordings/batch_check_exists': { results: { session_1: exists } },
                },
            })
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.REPLAY_EVENT_RECORDING_AVAILABILITY]: variant,
            })

            render(
                <Provider>
                    <ViewRecordingButton sessionId="session_1" recordingStatus={status} hasRecording={hasRecording} />
                </Provider>
            )

            if (variant === 'session_lookup') {
                await waitFor(() =>
                    expect(sessionRecordingInfoLogic.values.getRecordingExists('session_1')).toBe(exists)
                )
            }
            await waitFor(() =>
                expect(screen.getByRole('button', { name: 'View recording' })).toHaveAttribute(
                    'aria-disabled',
                    String(isDisabled)
                )
            )
            if (!isDisabled) {
                const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
                fireEvent.click(screen.getByRole('button', { name: 'View recording' }))
                expect(capture).toHaveBeenCalledWith('view_recording_clicked', {
                    availability_variant: variant,
                })
                capture.mockRestore()
            }
        }
    )

    it.each([
        ['active', true],
        ['active', undefined],
        [undefined, true],
    ])('does not look up an already enabled recording with status %s and existence %s', (status, hasRecording) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.REPLAY_EVENT_RECORDING_AVAILABILITY]: 'session_lookup',
        })

        render(
            <Provider>
                <ViewRecordingButton sessionId="session_1" recordingStatus={status} hasRecording={hasRecording} />
            </Provider>
        )

        expect(sessionRecordingInfoLogic.values.pendingFetches).toEqual({})
    })

    it.each([RecordingExistsState.NotExists, RecordingExistsState.Error])(
        'retries a %s lookup after its result expires',
        async (state) => {
            const now = jest.spyOn(Date, 'now').mockReturnValue(1_000)
            useMocks({
                post: {
                    '/api/projects/:team/session_recordings/batch_check_exists': { results: { session_1: true } },
                },
            })
            sessionRecordingInfoLogic.actions.recordExistence({ session_1: state })

            sessionRecordingInfoLogic.actions.checkRecordingInfo('session_1')
            expect(sessionRecordingInfoLogic.values.pendingFetches).toEqual({})

            now.mockReturnValue(31_001)
            sessionRecordingInfoLogic.actions.checkRecordingInfo('session_1')
            await waitFor(() => expect(sessionRecordingInfoLogic.values.getRecordingExists('session_1')).toBe(true))
            now.mockRestore()
        }
    )

    it('enables an earlier event when a recording appears after remount', async () => {
        const now = jest.spyOn(Date, 'now').mockReturnValue(1_000)
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.REPLAY_EVENT_RECORDING_AVAILABILITY]: 'session_lookup',
        })
        useMocks({
            post: {
                '/api/projects/:team/session_recordings/batch_check_exists': { results: { session_1: false } },
            },
        })

        render(
            <Provider>
                <ViewRecordingButton sessionId="session_1" recordingStatus="disabled" hasRecording={false} />
            </Provider>
        )
        await waitFor(() => expect(sessionRecordingInfoLogic.values.getRecordingExists('session_1')).toBe(false))
        cleanup()

        now.mockReturnValue(31_001)
        useMocks({
            post: {
                '/api/projects/:team/session_recordings/batch_check_exists': { results: { session_1: true } },
            },
        })
        render(
            <Provider>
                <ViewRecordingButton sessionId="session_1" recordingStatus="disabled" hasRecording={false} />
            </Provider>
        )

        await waitFor(() =>
            expect(screen.getByRole('button', { name: 'View recording' })).toHaveAttribute('aria-disabled', 'false')
        )
        now.mockRestore()
    })
})
