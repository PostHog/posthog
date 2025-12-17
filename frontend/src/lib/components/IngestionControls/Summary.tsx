import { match } from 'ts-pattern'

import { IconCheck, IconCircleDashed } from '@posthog/icons'
import { LemonBanner, Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils'

import { Trigger, TriggerType } from './types'

const summaryLabel: Record<TriggerType, string> = {
    [TriggerType.URL_MATCH]: 'URL matching',
    [TriggerType.EVENT]: 'Event triggers',
    [TriggerType.FEATURE_FLAG]: 'Feature flag',
    [TriggerType.SAMPLING]: 'Sampling rate',
    [TriggerType.MIN_DURATION]: 'Minimum duration',
    [TriggerType.URL_BLOCKLIST]: 'URL blocklist',
}

export function IngestionControlsSummary({ triggers }: { triggers: Trigger[] }): JSX.Element {
    const hasAnyTriggers = triggers.some((t) => t.enabled)

    return (
        <LemonBanner type="info" hideIcon>
            <div className="flex flex-col gap-1">
                <strong>{hasAnyTriggers ? 'Active triggers:' : 'No triggers — all sessions recorded'}</strong>
                <Link
                    to="https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record"
                    target="blank"
                >
                    Read about how to start and stop sessions in our docs.
                </Link>
                <div className="flex flex-col gap-0.5 mt-1">
                    {triggers.map((trigger, i) => (
                        <div key={i} className="flex items-center gap-2">
                            {trigger.enabled ? (
                                <IconCheck className="text-success" />
                            ) : (
                                <IconCircleDashed className="text-muted" />
                            )}
                            <span className={trigger.enabled ? '' : 'text-muted'}>
                                {summaryLabel[trigger.type]}
                                {trigger.enabled && <span className="text-muted"> ({triggerSummary(trigger)})</span>}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </LemonBanner>
    )
}

function triggerSummary(trigger: Trigger): string | null {
    return match(trigger)
        .with({ type: TriggerType.URL_MATCH }, (t) => pluralize(t.urls?.length || 0, 'pattern'))
        .with({ type: TriggerType.EVENT }, (t) => pluralize(t.events?.length || 0, 'event'))
        .with({ type: TriggerType.FEATURE_FLAG }, (t) => t.key)
        .with({ type: TriggerType.SAMPLING }, (t) => (t.sampleRate ? `${t.sampleRate}%` : 'N/A'))
        .with({ type: TriggerType.MIN_DURATION }, (t) => (t.minDurationMs ? `${t.minDurationMs / 1000}s` : 'N/A'))
        .with({ type: TriggerType.URL_BLOCKLIST }, (t) => pluralize(t.urls?.length || 0, 'pattern'))
        .run()
}
