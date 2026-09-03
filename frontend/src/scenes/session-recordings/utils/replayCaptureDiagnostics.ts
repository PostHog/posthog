import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'

export type DiagnosisVerdict =
    | 'captured'
    | 'ad_blocked'
    | 'disabled'
    | 'url_blocked'
    | 'recorder_not_started'
    | 'recorder_loading'
    | 'config_pending'
    | 'trigger_pending'
    | 'sampled_out'
    | 'buffering_empty'
    | 'recorder_error'
    | 'unknown'

export interface SuggestedAction {
    label: string
    to?: string
}

export interface DiagnosisContext {
    /** Every `$recording_status` the session reported, not only the one on this event. */
    sessionRecordingStatuses?: string[]
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
    '$session_recording_event_trigger_activated_session',
    '$sdk_debug_replay_url_trigger_status',
    '$sdk_debug_replay_event_trigger_status',
    '$sdk_debug_replay_linked_flag_trigger_status',
    '$sdk_debug_replay_trigger_groups_count',
    '$sdk_debug_replay_matched_recording_trigger_groups',
    '$sdk_debug_replay_internal_buffer_length',
    '$sdk_debug_replay_internal_buffer_size',
    '$sdk_debug_replay_flushed_size',
    '$sdk_debug_replay_remote_trigger_matching_config',
    '$sdk_debug_recording_script_not_loaded',
    '$sdk_debug_rrweb_start_attempted',
    '$sdk_debug_rrweb_attached',
    '$sdk_debug_replay_rrweb_error',
    '$sdk_debug_session_start',
    '$replay_sample_rate',
    '$replay_minimum_duration',
    '$replay_override_sampling',
    '$replay_override_linked_flag',
    '$replay_override_url_trigger',
    '$replay_override_event_trigger',
] as const

const TROUBLESHOOTING_URL = 'https://posthog.com/docs/session-replay/troubleshooting'

export function hasReplayDiagnosticSignals(properties: Record<string, any> | null | undefined): boolean {
    if (!properties) {
        return false
    }
    return DIAGNOSTIC_KEYS.some((key) => properties[key] !== undefined)
}

const pickSignals = (properties: Record<string, any>): Record<string, unknown> => {
    const out: Record<string, unknown> = {}
    for (const key of DIAGNOSTIC_KEYS) {
        if (properties[key] !== undefined) {
            out[key] = properties[key]
        }
    }
    return out
}

// posthog-js loads the recorder as a separate chunk. Until that chunk takes over, the SDK
// reports `disabled` and then `lazy_loading`, so the first events of a page load carry one of
// them on a session that records fine. Neither settles what the rest of the session did.
const STARTUP_STATUSES = ['disabled', 'lazy_loading']

// Statuses that say more than a startup snapshot, most to least informative: the first one the
// session reached wins.
const STATUSES_BEYOND_STARTUP = [
    'active',
    'sampled',
    'buffering',
    'rrweb_error',
    'paused',
    'missing_config',
    'awaiting_config',
    'pending_config',
    'lazy_loading',
]

const parseRemoteConfigEnabled = (value: unknown): boolean | null => {
    let config = value
    if (typeof config === 'string') {
        try {
            config = JSON.parse(config)
        } catch {
            return null
        }
    }
    if (config && typeof config === 'object' && typeof (config as Record<string, unknown>).enabled === 'boolean') {
        return (config as Record<string, boolean>).enabled
    }
    return null
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

export function diagnoseReplayCapture(
    eventProperties: Record<string, any> | null | undefined,
    context?: DiagnosisContext
): ReplayCaptureDiagnosis {
    const properties = eventProperties ?? {}
    const eventStatus = properties['$recording_status']
    const sessionStatuses = context?.sessionRecordingStatuses ?? []
    // The session got at least this far, even if this one event was captured before it did.
    const statusReachedLater = STARTUP_STATUSES.includes(eventStatus)
        ? STATUSES_BEYOND_STARTUP.find((s) => s !== eventStatus && sessionStatuses.includes(s))
        : undefined

    const diagnosis = diagnoseSignals(properties, statusReachedLater ?? eventStatus)
    if (!statusReachedLater) {
        return diagnosis
    }
    return {
        ...diagnosis,
        reasons: [
            `This event was captured before the recorder started. Later in the session the SDK reported ${statusReachedLater}.`,
            ...diagnosis.reasons,
        ],
    }
}

function diagnoseSignals(properties: Record<string, any>, recordingStatus: unknown): ReplayCaptureDiagnosis {
    const rawSignals = pickSignals(properties)

    const hasRecording = properties['$has_recording']
    const replayEnabledRemotely = parseRemoteConfigEnabled(properties['$session_recording_remote_config'])
    const startReason = properties['$session_recording_start_reason']
    const urlTrigger = properties['$sdk_debug_replay_url_trigger_status']
    const eventTrigger = properties['$sdk_debug_replay_event_trigger_status']
    const flagTrigger = properties['$sdk_debug_replay_linked_flag_trigger_status']
    const bufferLength = toNumber(properties['$sdk_debug_replay_internal_buffer_length'])
    const flushedSize = toNumber(properties['$sdk_debug_replay_flushed_size'])
    const scriptNotLoaded = properties['$sdk_debug_recording_script_not_loaded']
    const rrwebError = properties['$sdk_debug_replay_rrweb_error']

    const settingsAction: SuggestedAction = {
        label: 'Open replay settings',
        to: urls.settings('project-replay'),
    }
    const billingAction: SuggestedAction = {
        label: 'Open billing',
        to: urls.organizationBilling([ProductKey.SESSION_REPLAY]),
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

    // A reported rrweb error is the unambiguous signal that the recorder failed. The recorder is
    // started during buffering — before sampling/triggers resolve — so the attach flags alone
    // can't tell a real failure apart from a normal sampled-out or torn-down session.
    if (rrwebError || recordingStatus === 'rrweb_error') {
        return {
            verdict: 'recorder_error',
            headline: 'The recorder failed to start',
            reasons: [
                'The SDK started the rrweb recorder for this session but it reported an error, so no snapshots were produced.',
                ...(rrwebError
                    ? [`rrweb reported: ${typeof rrwebError === 'string' ? rrwebError : JSON.stringify(rrwebError)}.`]
                    : []),
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    if (recordingStatus === 'missing_config') {
        return {
            verdict: 'config_pending',
            headline: 'The SDK could not load its replay config',
            reasons: [
                'The SDK asked PostHog for fresh replay config, the request failed, and recording stays off until the page reloads.',
                'A blocked or failing request to the PostHog config endpoint is the usual cause. Check for ad blockers, a content security policy, or a reverse proxy that does not forward it.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    // Older SDKs call `awaiting_config` `pending_config`.
    if (recordingStatus === 'awaiting_config' || recordingStatus === 'pending_config') {
        return {
            verdict: 'config_pending',
            headline: 'The SDK was still waiting for its replay config',
            reasons: [
                'The SDK had asked PostHog for fresh replay config and had not received it yet, so the recorder had not started.',
                'Recording starts once the config arrives. A session that ends first produces no replay.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
        }
    }

    // PostHog returns replay as off both when the project has it turned off and when the
    // recordings quota is limited. The SDK stores both as `enabled: false`, so this property
    // cannot say which one applied.
    if (replayEnabledRemotely === false) {
        return {
            verdict: 'disabled',
            headline: 'PostHog told the SDK not to record this session',
            reasons: [
                'When this event was captured, PostHog was returning replay as off, so the recorder never started.',
                'Two things cause this: replay is turned off for the project, or the organization has reached its recording quota. This event does not say which one.',
                'Check replay settings first. If replay is already on there, check billing for a recording limit.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, billingAction, troubleshootingAction],
        }
    }

    // The SDK returns `paused` from one condition in every status path: the current URL matches
    // the project's blocked list. It is checked before triggers there, so it is checked first here.
    if (recordingStatus === 'paused') {
        return {
            verdict: 'url_blocked',
            headline: 'Recording is turned off for this page',
            reasons: [
                'The page URL matches the blocked URLs list for this project, so the SDK stopped recording while the visitor was on it.',
                'Check the blocked URLs list in replay settings if this page should be recorded.',
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

    if (recordingStatus === 'lazy_loading') {
        return {
            verdict: 'recorder_loading',
            headline: 'The recorder had not finished loading yet',
            reasons: [
                'PostHog loads the recorder as a separate file after the SDK starts. When this event was captured, that file had not taken over yet, so the recorder was not producing snapshots.',
                'This is normal early in a page load. If the visit ended around this point, that is the likely reason there is no recording. Short visits and slow networks are the usual cause, and it is not a settings problem.',
            ],
            rawSignals,
            suggestedActions: [troubleshootingAction],
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

    if (recordingStatus === 'disabled') {
        return {
            verdict: 'recorder_not_started',
            headline: 'The recorder was not running for this session',
            reasons: [
                'The SDK reports this state both when replay is turned off and before the recorder has loaded, so it does not on its own mean replay is off.',
                replayEnabledRemotely === true
                    ? 'Replay is on for this project, so look at the SDK setup on the page rather than project settings.'
                    : 'Check that replay is on in project settings.',
                'On the page, check that disable_session_recording is not set, that the visitor has not opted out, and that nothing blocks the recorder file.',
            ],
            rawSignals,
            suggestedActions: [settingsAction, troubleshootingAction],
        }
    }

    if ((recordingStatus === 'active' || recordingStatus === 'sampled') && flushedSize !== null && flushedSize > 0) {
        return {
            verdict: 'captured',
            headline: 'A recording should exist for this session',
            reasons: [
                `The SDK reported \`$recording_status = ${recordingStatus}\` and flushed recording data to PostHog.`,
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
