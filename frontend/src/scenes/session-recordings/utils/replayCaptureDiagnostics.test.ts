import { DiagnosisVerdict, diagnoseReplayCapture, hasReplayDiagnosticSignals } from './replayCaptureDiagnostics'

type Case = {
    name: string
    properties: Record<string, any>
    expected: DiagnosisVerdict
}

describe('diagnoseReplayCapture', () => {
    const verdictCases: Case[] = [
        {
            name: '$has_recording=true short-circuits to captured',
            properties: { $has_recording: true, $recording_status: 'disabled' },
            expected: 'captured',
        },
        {
            name: '$has_recording=false does not short-circuit — falls through to other rules',
            properties: { $has_recording: false, $recording_status: 'disabled' },
            expected: 'recorder_not_started',
        },
        {
            name: 'ad blocker prevented script load',
            properties: { $sdk_debug_recording_script_not_loaded: true },
            expected: 'ad_blocked',
        },
        {
            name: 'a disabled snapshot alone is not read as replay being off',
            properties: { $recording_status: 'disabled' },
            expected: 'recorder_not_started',
        },
        {
            name: 'remote config proves replay is off for the project',
            properties: { $recording_status: 'disabled', $session_recording_remote_config: { enabled: false } },
            expected: 'disabled',
        },
        {
            name: 'remote config arrives as a JSON string',
            properties: { $recording_status: 'disabled', $session_recording_remote_config: '{"enabled": false}' },
            expected: 'disabled',
        },
        {
            name: 'replay on for the project means a disabled snapshot is not a settings problem',
            properties: { $recording_status: 'disabled', $session_recording_remote_config: { enabled: true } },
            expected: 'recorder_not_started',
        },
        {
            name: 'recorder chunk still loading',
            properties: { $recording_status: 'lazy_loading' },
            expected: 'recorder_loading',
        },
        {
            name: 'waiting on fresh remote config',
            properties: { $recording_status: 'awaiting_config' },
            expected: 'config_pending',
        },
        {
            name: 'older SDKs name the waiting state pending_config',
            properties: { $recording_status: 'pending_config' },
            expected: 'config_pending',
        },
        {
            name: 'remote config could not be loaded',
            properties: { $recording_status: 'missing_config' },
            expected: 'config_pending',
        },
        {
            name: 'rrweb_error status without an error message',
            properties: { $recording_status: 'rrweb_error' },
            expected: 'recorder_error',
        },
        {
            name: 'URL trigger is pending and nothing matched',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_url_trigger_status: 'trigger_pending',
                $sdk_debug_replay_event_trigger_status: 'trigger_disabled',
                $sdk_debug_replay_linked_flag_trigger_status: 'trigger_disabled',
            },
            expected: 'trigger_pending',
        },
        {
            name: 'event trigger pending takes precedence over buffering-empty',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_url_trigger_status: 'trigger_disabled',
                $sdk_debug_replay_event_trigger_status: 'trigger_pending',
                $sdk_debug_replay_linked_flag_trigger_status: 'trigger_disabled',
                $sdk_debug_replay_internal_buffer_length: 0,
            },
            expected: 'trigger_pending',
        },
        {
            name: 'linked flag pending but URL matched → not trigger_pending',
            properties: {
                $recording_status: 'active',
                $sdk_debug_replay_url_trigger_status: 'trigger_matched',
                $sdk_debug_replay_linked_flag_trigger_status: 'trigger_pending',
                $sdk_debug_replay_flushed_size: 1024,
            },
            expected: 'captured',
        },
        {
            name: 'sampled means sampled in, so flushed data reads as captured',
            properties: {
                $recording_status: 'sampled',
                $sdk_debug_replay_flushed_size: 2048,
            },
            expected: 'captured',
        },
        {
            name: 'paused is the URL blocklist state',
            properties: { $recording_status: 'paused' },
            expected: 'url_blocked',
        },
        {
            name: 'a blocked URL outranks a pending trigger',
            properties: {
                $recording_status: 'paused',
                $sdk_debug_replay_url_trigger_status: 'trigger_pending',
            },
            expected: 'url_blocked',
        },
        {
            name: 'replay being off for the project outranks a blocked URL',
            properties: {
                $recording_status: 'paused',
                $session_recording_remote_config: { enabled: false },
            },
            expected: 'disabled',
        },
        {
            name: 'sampled out via start reason',
            properties: { $session_recording_start_reason: 'sampled_out' },
            expected: 'sampled_out',
        },
        {
            name: 'buffering with empty buffer and no flushed data',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_internal_buffer_length: 0,
                $sdk_debug_replay_flushed_size: 0,
            },
            expected: 'buffering_empty',
        },
        {
            name: 'active with flushed bytes → captured',
            properties: {
                $recording_status: 'active',
                $sdk_debug_replay_flushed_size: 2048,
                $session_recording_start_reason: 'recording_initialized',
            },
            expected: 'captured',
        },
        {
            name: 'reported rrweb error → recorder_error',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_rrweb_error: 'TypeError: boom',
            },
            expected: 'recorder_error',
        },
        {
            name: 'rrweb error outranks a pending trigger',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_event_trigger_status: 'trigger_pending',
                $sdk_debug_replay_rrweb_error: 'boom',
            },
            expected: 'recorder_error',
        },
        {
            // rrweb is started during buffering, so an unattached recorder with no reported error
            // is a normal sampled-out / torn-down session, not a failure.
            name: 'unattached recorder without an error is not mislabelled as recorder_error',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_rrweb_start_attempted: true,
                $sdk_debug_rrweb_attached: false,
                $session_recording_start_reason: 'sampled_out',
            },
            expected: 'sampled_out',
        },
        {
            name: 'string-valued flushed size is coerced to a number',
            properties: {
                $recording_status: 'active',
                $sdk_debug_replay_flushed_size: '2048',
            },
            expected: 'captured',
        },
        {
            name: 'empty properties object → unknown',
            properties: {},
            expected: 'unknown',
        },
        {
            name: 'null properties → unknown',
            properties: null as any,
            expected: 'unknown',
        },
        {
            name: 'undefined properties → unknown',
            properties: undefined as any,
            expected: 'unknown',
        },
        {
            name: 'ad_blocked takes priority over disabled when both present',
            properties: {
                $sdk_debug_recording_script_not_loaded: true,
                $recording_status: 'disabled',
            },
            expected: 'ad_blocked',
        },
        {
            // posthog-js never writes `sampled_out`; this only pins the rule order for an SDK that does.
            name: 'an explicit sampled_out reason outranks a disabled snapshot',
            properties: {
                $recording_status: 'disabled',
                $session_recording_start_reason: 'sampled_out',
            },
            expected: 'sampled_out',
        },
        {
            name: 'a trigger group that matched then sampled the session out reads as sampled_out',
            properties: {
                $recording_status: 'disabled',
                $session_recording_remote_config: { enabled: true },
                $sdk_debug_replay_matched_recording_trigger_groups: [
                    { id: 'g1', name: 'Checkout', matched: true, sampled: false },
                ],
            },
            expected: 'sampled_out',
        },
        {
            name: 'a trigger group that sampled the session in is not read as sampled_out',
            properties: {
                $recording_status: 'disabled',
                $sdk_debug_replay_matched_recording_trigger_groups: [
                    { id: 'g1', name: 'Checkout', matched: true, sampled: true },
                ],
            },
            expected: 'recorder_not_started',
        },
        {
            name: 'no matched trigger groups is not read as sampled_out',
            properties: {
                $recording_status: 'disabled',
                $sdk_debug_replay_matched_recording_trigger_groups: [],
            },
            expected: 'recorder_not_started',
        },
        {
            name: 'replay being off for the project outranks a sampled-out trigger group',
            properties: {
                $recording_status: 'disabled',
                $session_recording_remote_config: { enabled: false },
                $sdk_debug_replay_matched_recording_trigger_groups: [
                    { id: 'g1', name: 'Checkout', matched: true, sampled: false },
                ],
            },
            expected: 'disabled',
        },
        {
            name: 'a session posthog-js dropped by sampling still reads as recorder_not_started',
            properties: {
                $recording_status: 'disabled',
                $replay_sample_rate: 0.1,
            },
            expected: 'recorder_not_started',
        },
        {
            name: 'replay being off for the project outranks sampling',
            properties: {
                $recording_status: 'disabled',
                $session_recording_remote_config: { enabled: false },
                $session_recording_start_reason: 'sampled_out',
            },
            expected: 'disabled',
        },
        {
            name: 'multiple triggers pending lists all in reasons',
            properties: {
                $sdk_debug_replay_url_trigger_status: 'trigger_pending',
                $sdk_debug_replay_event_trigger_status: 'trigger_pending',
                $sdk_debug_replay_linked_flag_trigger_status: 'trigger_disabled',
            },
            expected: 'trigger_pending',
        },
        {
            name: 'all three triggers pending',
            properties: {
                $sdk_debug_replay_url_trigger_status: 'trigger_pending',
                $sdk_debug_replay_event_trigger_status: 'trigger_pending',
                $sdk_debug_replay_linked_flag_trigger_status: 'trigger_pending',
            },
            expected: 'trigger_pending',
        },
        {
            name: 'buffering with non-zero buffer length does not match buffering_empty',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_internal_buffer_length: 5,
                $sdk_debug_replay_flushed_size: 0,
            },
            expected: 'unknown',
        },
        {
            name: 'buffering with null buffer length and null flushed size → unknown (not buffering_empty)',
            properties: {
                $recording_status: 'buffering',
            },
            expected: 'unknown',
        },
        {
            name: 'active with zero flushed size → unknown (not captured)',
            properties: {
                $recording_status: 'active',
                $sdk_debug_replay_flushed_size: 0,
            },
            expected: 'unknown',
        },
        {
            name: 'active with no flushed size property → unknown',
            properties: {
                $recording_status: 'active',
            },
            expected: 'unknown',
        },
        {
            name: 'string-valued buffer length "0" is coerced for buffering_empty',
            properties: {
                $recording_status: 'buffering',
                $sdk_debug_replay_internal_buffer_length: '0',
                $sdk_debug_replay_flushed_size: '0',
            },
            expected: 'buffering_empty',
        },
        {
            name: 'empty string flushed size is not coerced to a number',
            properties: {
                $recording_status: 'active',
                $sdk_debug_replay_flushed_size: '',
            },
            expected: 'unknown',
        },
    ]

    it.each(verdictCases)('$name → $expected', ({ properties, expected }) => {
        const result = diagnoseReplayCapture(properties)
        expect(result.verdict).toBe(expected)
        expect(result.headline).toBeTruthy()
        expect(result.reasons.length).toBeGreaterThan(0)
    })

    it.each([
        ['lazy_loading', 'recorder_loading'],
        ['paused', 'url_blocked'],
        ['active', 'recorder_ran'],
        ['buffering', 'recorder_ran'],
        ['sampled', 'recorder_ran'],
    ])('a disabled event is re-read against the %s the session reported', (sessionStatus, expected) => {
        const properties = { $recording_status: 'disabled' }

        expect(diagnoseReplayCapture(properties).verdict).toBe('recorder_not_started')

        const result = diagnoseReplayCapture(properties, {
            sessionRecordingStatuses: ['disabled', sessionStatus],
        })
        expect(result.verdict).toBe(expected)
        expect(result.reasons[0]).toContain(sessionStatus)
        // The endpoint returns the statuses without timestamps, so no verdict may claim an order.
        expect([result.headline, ...result.reasons].join(' ')).not.toMatch(/later in the session/i)
    })

    it('keeps a cause this event proves over the session reporting the recorder ran', () => {
        const result = diagnoseReplayCapture(
            { $recording_status: 'disabled', $session_recording_remote_config: { enabled: false } },
            { sessionRecordingStatuses: ['disabled', 'active'] }
        )
        expect(result.verdict).toBe('disabled')
    })

    it('re-reads a lazy_loading event against a session that got further', () => {
        const properties = { $recording_status: 'lazy_loading' }

        expect(diagnoseReplayCapture(properties).verdict).toBe('recorder_loading')

        const result = diagnoseReplayCapture(properties, {
            sessionRecordingStatuses: ['lazy_loading', 'active'],
        })
        expect(result.verdict).not.toBe('recorder_loading')
        expect(result.reasons[0]).toContain('active')
    })

    it('keeps the recorder_loading verdict when the session never got past loading', () => {
        const result = diagnoseReplayCapture(
            { $recording_status: 'lazy_loading' },
            { sessionRecordingStatuses: ['disabled', 'lazy_loading'] }
        )
        expect(result.verdict).toBe('recorder_loading')
        expect(result.reasons[0]).not.toContain('elsewhere in the session')
    })

    it.each(['lazy_loading', 'disabled'])('a %s snapshot alone does not claim the session ended', (status) => {
        const result = diagnoseReplayCapture({ $recording_status: status })
        expect([result.headline, ...result.reasons].join(' ')).not.toMatch(/session ended/i)
    })

    it('keeps the disabled verdict when the whole session agrees', () => {
        const result = diagnoseReplayCapture(
            { $recording_status: 'disabled', $session_recording_remote_config: { enabled: false } },
            { sessionRecordingStatuses: ['disabled'] }
        )
        expect(result.verdict).toBe('disabled')
        expect(result.reasons[0]).not.toContain('elsewhere in the session')
    })

    it('includes relevant raw signals in the result', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'active',
            $sdk_debug_replay_flushed_size: 500,
            $unrelated_property: 'should not appear',
        })
        expect(result.rawSignals).toEqual({
            $recording_status: 'active',
            $sdk_debug_replay_flushed_size: 500,
        })
    })

    it('includes settings action for disabled verdict', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'disabled',
            $session_recording_remote_config: { enabled: false },
        })
        const labels = result.suggestedActions.map((a) => a.label)
        expect(labels).toContain('Open replay settings')
        expect(labels).toContain('Read troubleshooting docs')
    })

    it('names sampling when the recorder did not start and the sample rate is below 1', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'disabled',
            $replay_sample_rate: 0.1,
        })
        expect(result.verdict).toBe('recorder_not_started')
        expect(result.reasons.join(' ')).toContain('10%')
    })

    it('names the trigger group sample rate when a V2 group sampled the session out', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'disabled',
            $sdk_debug_replay_matched_recording_trigger_groups: [
                { id: 'g1', name: 'Checkout', matched: true, sampled: false },
            ],
        })

        expect(result.verdict).toBe('sampled_out')
        expect(result.reasons.join(' ')).toMatch(/trigger group/i)
        expect(result.reasons.join(' ')).toMatch(/raise the sample rate/i)
    })

    it('does not mention sampling when every session is sampled in', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'disabled',
            $replay_sample_rate: 1,
        })
        expect(result.reasons.join(' ')).not.toMatch(/sampling/i)
    })

    it('does not blame project settings alone when replay comes back off', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'disabled',
            $session_recording_remote_config: { enabled: false },
        })
        const text = [result.headline, ...result.reasons].join(' ')
        expect(text).toMatch(/quota/i)
        expect(result.suggestedActions.map((a) => a.label)).toContain('Open billing')
    })

    it('does not include settings action for captured verdict', () => {
        const result = diagnoseReplayCapture({ $has_recording: true })
        const labels = result.suggestedActions.map((a) => a.label)
        expect(labels).not.toContain('Open replay settings')
        expect(labels).toContain('Read troubleshooting docs')
    })

    it('trigger_pending reason mentions all pending trigger names', () => {
        const result = diagnoseReplayCapture({
            $sdk_debug_replay_url_trigger_status: 'trigger_pending',
            $sdk_debug_replay_event_trigger_status: 'trigger_pending',
            $sdk_debug_replay_linked_flag_trigger_status: 'trigger_disabled',
        })
        expect(result.reasons[0]).toContain('URL trigger')
        expect(result.reasons[0]).toContain('event trigger')
        expect(result.reasons[0]).not.toContain('linked flag trigger')
    })

    it('recorder_error surfaces the rrweb error message when present', () => {
        const result = diagnoseReplayCapture({
            $recording_status: 'buffering',
            $sdk_debug_replay_rrweb_error: 'boom',
        })
        expect(result.verdict).toBe('recorder_error')
        expect(result.reasons.some((r) => r.includes('boom'))).toBe(true)
    })

    it('preserves newly added replay debug keys in rawSignals', () => {
        const result = diagnoseReplayCapture({
            $replay_override_sampling: true,
            $sdk_debug_rrweb_attached: false,
            $sdk_debug_replay_trigger_groups_count: 3,
            $session_recording_event_trigger_activated_session: 'abc',
            $not_a_signal: 'ignored',
        })
        expect(result.rawSignals).toHaveProperty('$replay_override_sampling')
        expect(result.rawSignals).toHaveProperty('$sdk_debug_rrweb_attached')
        expect(result.rawSignals).toHaveProperty('$sdk_debug_replay_trigger_groups_count')
        expect(result.rawSignals).toHaveProperty('$session_recording_event_trigger_activated_session')
        expect(result.rawSignals).not.toHaveProperty('$not_a_signal')
    })

    it('preserves all known diagnostic keys in rawSignals', () => {
        const properties = {
            $has_recording: false,
            $recording_status: 'active',
            $session_recording_start_reason: 'recording_initialized',
            $replay_sample_rate: 0.5,
            $replay_minimum_duration: 3000,
            $sdk_debug_session_start: '2024-01-01T00:00:00Z',
            $some_other_prop: 'ignored',
        }
        const result = diagnoseReplayCapture(properties)
        expect(result.rawSignals).toHaveProperty('$has_recording')
        expect(result.rawSignals).toHaveProperty('$recording_status')
        expect(result.rawSignals).toHaveProperty('$session_recording_start_reason')
        expect(result.rawSignals).toHaveProperty('$replay_sample_rate')
        expect(result.rawSignals).toHaveProperty('$replay_minimum_duration')
        expect(result.rawSignals).toHaveProperty('$sdk_debug_session_start')
        expect(result.rawSignals).not.toHaveProperty('$some_other_prop')
    })
})

describe('hasReplayDiagnosticSignals', () => {
    it('returns false for nullish or empty properties', () => {
        expect(hasReplayDiagnosticSignals(undefined)).toBe(false)
        expect(hasReplayDiagnosticSignals(null)).toBe(false)
        expect(hasReplayDiagnosticSignals({})).toBe(false)
    })

    it('returns false when no recording diagnostic signals are present', () => {
        expect(hasReplayDiagnosticSignals({ $browser: 'Chrome', some_custom_prop: 1 })).toBe(false)
    })

    it('returns true when at least one recording diagnostic signal is present', () => {
        expect(hasReplayDiagnosticSignals({ $recording_status: 'buffering' })).toBe(true)
        expect(hasReplayDiagnosticSignals({ $sdk_debug_replay_event_trigger_status: 'trigger_pending' })).toBe(true)
        expect(hasReplayDiagnosticSignals({ $has_recording: false })).toBe(true)
    })
})
