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

export function IngestionControlsSummary({
    triggers,
    controlDescription,
    docsLink,
}: {
    triggers: Trigger[]
    controlDescription: string
    docsLink?: {
        to: string
        label: string
    }
}): JSX.Element {
    const hasAnyTriggers = triggers.some((t) => t.enabled)

    return (
        <LemonBanner type="info" hideIcon>
            <div className="flex flex-col gap-1">
                <h3 className="mb-0">
                    {hasAnyTriggers ? 'Trigger summary' : `No triggers — all ${controlDescription}`}
                </h3>
                {docsLink && (
                    <Link to={docsLink.to} target="blank">
                        {docsLink.label}
                    </Link>
                )}
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
        .with({ type: TriggerType.SAMPLING }, (t) => (t.sampleRate ? `${t.sampleRate * 100}%` : 'N/A'))
        .with({ type: TriggerType.MIN_DURATION }, (t) => (t.minDurationMs ? `${t.minDurationMs / 1000}s` : 'N/A'))
        .with({ type: TriggerType.URL_BLOCKLIST }, (t) => pluralize(t.urls?.length || 0, 'pattern'))
        .run()
}
