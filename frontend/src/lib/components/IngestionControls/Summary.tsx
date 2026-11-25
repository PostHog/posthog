import { IconCheck, IconCircleDashed } from '@posthog/icons'
import { LemonBanner, Link } from '@posthog/lemon-ui'

import { summaryLabel, triggerSummary } from './triggerSummary'
import { Trigger } from './types'

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
