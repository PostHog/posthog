import { DiagnosisVerdict, diagnoseReplayCapture } from './replayCaptureDiagnostics'

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
            expected: 'disabled',
        },
        {
            name: 'ad blocker prevented script load',
            properties: { $sdk_debug_recording_script_not_loaded: true },
            expected: 'ad_blocked',
        },
        {
            name: 'recording explicitly disabled',
            properties: { $recording_status: 'disabled' },
            expected: 'disabled',
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
            name: 'sampled status means sampled in — not sampled out',
            properties: { $recording_status: 'sampled' },
            expected: 'unknown',
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
            name: 'disabled takes priority over sampled when both present',
            properties: {
                $recording_status: 'disabled',
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
            name: 'paused recording status → unknown',
            properties: {
                $recording_status: 'paused',
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
        const result = diagnoseReplayCapture({ $recording_status: 'disabled' })
        const labels = result.suggestedActions.map((a) => a.label)
        expect(labels).toContain('Open replay settings')
        expect(labels).toContain('Read troubleshooting docs')
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
