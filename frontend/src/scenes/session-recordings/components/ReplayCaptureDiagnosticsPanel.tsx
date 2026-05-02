import { useValues } from 'kea'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { LemonBanner, LemonBannerProps } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { DiagnosisVerdict, ReplayCaptureDiagnosis, diagnoseReplayCapture } from '../utils/replayCaptureDiagnostics'
import { replayCaptureDiagnosticsPanelLogic } from './replayCaptureDiagnosticsPanelLogic'

type ReplayCaptureDiagnosticsPanelProps =
    | { eventProperties: Record<string, any>; sessionId?: undefined }
    | { sessionId: string; eventProperties?: undefined }

const TRIGGER_STATUS_EXPLANATIONS: Record<string, string> = {
    trigger_disabled: 'No trigger of this type is configured.',
    trigger_pending: 'A trigger is configured but has not yet matched on this session.',
    trigger_matched: 'The trigger fired — recording was allowed to start.',
}

const RECORDING_STATUS_EXPLANATIONS: Record<string, string> = {
    active: 'The SDK is recording and producing snapshots.',
    buffering:
        'The SDK initialized but is waiting (for a trigger, duration, or remote config) before producing snapshots.',
    disabled: 'Recording is turned off — either in project settings or via SDK config at runtime.',
    sampled: 'This session was included by the configured replay sample rate — recording started.',
    paused: 'Recording is temporarily paused for this session.',
}

const START_REASON_EXPLANATIONS: Record<string, string> = {
    recording_initialized: 'Recording started as soon as the SDK initialized.',
    sampling_override: 'Recording started because the session was included by the sampling rules.',
    sampled_out: 'Recording was prevented because the session was excluded by sampling.',
    linked_flag_match: 'Recording started because a linked feature flag matched.',
}

const explainValue = (key: string, value: unknown): string | null => {
    if (typeof value !== 'string') {
        return null
    }
    switch (key) {
        case '$recording_status':
            return RECORDING_STATUS_EXPLANATIONS[value] ?? null
        case '$session_recording_start_reason':
            return START_REASON_EXPLANATIONS[value] ?? null
        case '$sdk_debug_replay_url_trigger_status':
        case '$sdk_debug_replay_event_trigger_status':
        case '$sdk_debug_replay_linked_flag_trigger_status':
            return TRIGGER_STATUS_EXPLANATIONS[value] ?? null
        case '$sdk_debug_recording_script_not_loaded':
            return 'The SDK reported the recorder script was not loaded on the page — often caused by ad blockers.'
        default:
            return null
    }
}

function ExplainedSignalList({ signals }: { signals: Record<string, unknown> }): JSX.Element {
    const entries = Object.entries(signals)
    if (entries.length === 0) {
        return <div className="text-xs text-muted">No diagnostic signals on this event.</div>
    }
    return (
        <div className="text-xs deprecated-space-y-2">
            {entries.map(([key, value]) => {
                const explanation = explainValue(key, value)
                const display = typeof value === 'object' ? JSON.stringify(value) : String(value)
                return (
                    <div key={key} className="flex flex-col">
                        <div className="flex gap-2 items-baseline justify-between">
                            <span className="font-semibold">
                                <PropertyKeyInfo value={key} />
                            </span>
                            <pre className="text-primary-alt break-all mb-0">{display}</pre>
                        </div>
                        {explanation && <span className="text-muted italic pl-2">{explanation}</span>}
                    </div>
                )
            })}
        </div>
    )
}

const BANNER_TYPE_BY_VERDICT: Record<DiagnosisVerdict, LemonBannerProps['type']> = {
    captured: 'success',
    ad_blocked: 'warning',
    disabled: 'warning',
    trigger_pending: 'info',
    sampled_out: 'info',
    buffering_empty: 'info',
    unknown: 'info',
}

function DiagnosisContent({ diagnosis }: { diagnosis: ReplayCaptureDiagnosis }): JSX.Element {
    return (
        <LemonBanner type={BANNER_TYPE_BY_VERDICT[diagnosis.verdict]} className="text-left">
            <div className="deprecated-space-y-2">
                <div className="font-semibold">{diagnosis.headline}</div>
                <ul className="list-disc pl-4 deprecated-space-y-1 text-xs">
                    {diagnosis.reasons.map((reason, idx) => (
                        <li key={idx}>{reason}</li>
                    ))}
                </ul>
                {diagnosis.suggestedActions.length > 0 && (
                    <div className="flex gap-2 flex-wrap">
                        {diagnosis.suggestedActions.map((action, idx) => (
                            <LemonButton
                                key={idx}
                                type="secondary"
                                size="small"
                                to={action.to}
                                targetBlank={action.to?.startsWith('http')}
                            >
                                {action.label}
                            </LemonButton>
                        ))}
                    </div>
                )}
                {Object.keys(diagnosis.rawSignals).length > 0 && (
                    <LemonCollapse
                        size="small"
                        panels={[
                            {
                                key: 'raw-signals',
                                header: 'Raw diagnostic signals',
                                content: <ExplainedSignalList signals={diagnosis.rawSignals} />,
                            },
                        ]}
                    />
                )}
            </div>
        </LemonBanner>
    )
}

export function ReplayCaptureDiagnosticsPanel(props: ReplayCaptureDiagnosticsPanelProps): JSX.Element | null {
    if (props.eventProperties) {
        return <DiagnosisContent diagnosis={diagnoseReplayCapture(props.eventProperties)} />
    }

    return <SessionIdDiagnosticsPanel sessionId={props.sessionId} />
}

function SessionIdDiagnosticsPanel({ sessionId }: { sessionId: string }): JSX.Element | null {
    const { sessionEventProperties, sessionEventPropertiesLoading } = useValues(
        replayCaptureDiagnosticsPanelLogic({ sessionId })
    )

    if (sessionEventPropertiesLoading) {
        return (
            <div className="flex justify-center items-center p-4">
                <Spinner />
                <span className="ml-2 text-xs text-muted">Loading capture diagnostics…</span>
            </div>
        )
    }

    if (!sessionEventProperties) {
        return null
    }

    return <DiagnosisContent diagnosis={diagnoseReplayCapture(sessionEventProperties)} />
}
