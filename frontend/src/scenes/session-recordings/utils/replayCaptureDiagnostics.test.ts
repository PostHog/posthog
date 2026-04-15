import { DiagnosisVerdict, diagnoseReplayCapture } from './replayCaptureDiagnostics'

type Case = {
    name: string
    properties: Record<string, any>
    expected: DiagnosisVerdict
}

describe('diagnoseReplayCapture', () => {
    const cases: Case[] = [
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
            name: 'sampled out via recording_status',
            properties: { $recording_status: 'sampled' },
            expected: 'sampled_out',
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
    ]

    it.each(cases)('$name → $expected', ({ properties, expected }) => {
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
})
