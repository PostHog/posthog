import { urls } from 'scenes/urls'

export type DiagnosisVerdict =
    | 'captured'
    | 'ad_blocked'
    | 'disabled'
    | 'trigger_pending'
    | 'sampled_out'
    | 'buffering_empty'
    | 'unknown'

export interface SuggestedAction {
    label: string
    to?: string
}

export interface ReplayCaptureDiagnosis {
    verdict: DiagnosisVerdict
    headline: string
    reasons: string[]
    rawSignals: Record<string, unknown>
    suggestedActions: SuggestedAction[]
}

const DIAGNOSTIC_KEYS = [
    '$has_recording',
    '$recording_status',
    '$session_recording_start_reason',
    '$session_recording_url_trigger_activated_session',
    '$session_recording_url_trigger_status',
    '$session_recording_remote_config',
    '$sdk_debug_replay_url_trigger_status',
    '$sdk_debug_replay_event_trigger_status',
    '$sdk_debug_replay_linked_flag_trigger_status',
    '$sdk_debug_replay_internal_buffer_length',
    '$sdk_debug_replay_internal_buffer_size',
    '$sdk_debug_replay_flushed_size',
    '$sdk_debug_replay_remote_trigger_matching_config',
    '$sdk_debug_recording_script_not_loaded',
    '$sdk_debug_session_start',
    '$replay_sample_rate',
    '$replay_minimum_duration',
] as const

const TROUBLESHOOTING_URL = 'https://posthog.com/docs/session-replay/troubleshooting'

const pickSignals = (properties: Record<string, any>): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const key of DIAGNOSTIC_KEYS) {
        if (properties[key] !== undefined) {
            out[key] = properties[key]
        }
    }
    return out
}

const toNumber = (value: unknown): number | null => {
    if (typeof value === 'number') {
        return value
    }
    if (typeof value === 'string' && value.trim() !== '' && !isNaN(Number(value))) {
        return Number(value)
    }
    return null
}

export function diagnoseReplayCapture(eventProperties: Record<string, any> | null | undefined): ReplayCaptureDiagnosis {
    const properties = eventProperties ?? {}
    const rawSignals = pickSignals(properties)

    const hasRecording = properties['$has_recording']
    const recordingStatus = properties['$recording_status']
    const startReason = properties['$session_recording_start_reason']
    const urlTrigger = properties['$sdk_debug_replay_url_trigger_status']
    const eventTrigger = properties['$sdk_debug_replay_event_trigger_status']
    const flagTrigger = properties['$sdk_debug_replay_linked_flag_trigger_status']
    const bufferLength = toNumber(properties['$sdk_debug_replay_internal_buffer_length'])
    const flushedSize = toNumber(properties['$sdk_debug_replay_flushed_size'])
    const scriptNotLoaded = properties['$sdk_debug_recording_script_not_loaded']

    const settingsAction: SuggestedAction = {
        label: 'Open replay settings',
        to: urls.settings('project-replay'),
    }
    const troubleshootingAction: SuggestedAction = {
        label: 'Read troubleshooting docs',
        to: TROUBLESHOOTING_URL,
    }

    if (hasRecording === true) {
        return {
            verdict: 'captured',
            headline: 'A recording exists for this session',
            reasons: [
                'PostHog has a stored recording linked to this event\u2019s session (`$has_recording = true`).',
                'If the replay still appears missing in the UI, try refreshing — it may still be processing.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    if (scriptNotLoaded) {
        return {
            verdict: 'ad_blocked',
            headline: 'The recording script failed to load — likely blocked by an ad blocker',
            reasons: [
                'The SDK reported that the recorder script was not loaded on the page.',
                'This is usually caused by a browser ad blocker or content security policy blocking the recorder asset.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    if (recordingStatus === 'disabled') {
        return {
            verdict: 'disabled',
            headline: 'Session recording was disabled for this session',
            reasons: [
                'The SDK reported `$recording_status = disabled` at the time this event was captured.',
                'Recording may be turned off in project settings, or explicitly disabled at runtime via the SDK.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, troubleshootingAction],
        }
    }

    const triggers = [
        { key: 'URL trigger', status: urlTrigger },
        { key: 'event trigger', status: eventTrigger },
        { key: 'linked flag trigger', status: flagTrigger },
    ]
    const anyMatched = triggers.some((t) => t.status === 'trigger_matched')
    const pending = triggers.filter((t) => t.status === 'trigger_pending')
    if (!anyMatched && pending.length > 0) {
        return {
            verdict: 'trigger_pending',
            headline: `Recording was gated on a trigger that never fired`,
            reasons: [
                `The following trigger(s) were pending and never matched: ${pending.map((p) => p.key).join(', ')}.`,
                'Recording only starts once a configured trigger is satisfied — until then, no snapshots are captured.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, troubleshootingAction],
        }
    }

    if (startReason === 'sampled_out') {
        return {
            verdict: 'sampled_out',
            headline: 'This session was excluded by sampling',
            reasons: [
                'The SDK selected this session to be dropped based on the configured replay sample rate.',
                'Sampling is random per-session — increase the sample rate in project settings to capture more sessions.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, troubleshootingAction],
        }
    }

    if (recordingStatus === 'buffering' && bufferLength === 0 && (flushedSize === null || flushedSize === 0)) {
        return {
            verdict: 'buffering_empty',
            headline: 'Recording initialized but no snapshots were produced',
            reasons: [
                'The SDK was buffering but the internal buffer was empty and nothing has been flushed yet.',
                'This can happen if the page navigated or closed before the recorder produced its first snapshot, or if a minimum-duration config was not met.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, troubleshootingAction],
        }
    }

    if (recordingStatus === 'active' && flushedSize !== null && flushedSize > 0) {
        return {
            verdict: 'captured',
            headline: 'A recording should exist for this session',
            reasons: [
                'The SDK reported `$recording_status = active` and flushed recording data to PostHog.',
                'If the replay still appears missing, it may still be processing, or it may have been deleted due to retention.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    return {
        verdict: 'unknown',
        headline: 'Unable to determine why this recording is missing',
        reasons: [
            'The diagnostic properties on this event do not match any known capture-failure pattern.',
            'Check the raw signals below and the troubleshooting docs for more guidance.',
        ],
        rawSignals,
        suggestedActions: [settingsAction, troubleshootingAction],
    }
}
