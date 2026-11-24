import { IconCheckCircle, IconClock, IconMinusSquare, IconWarning } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import {
    AIObservabilityInstrumentationCheckEnumApi,
    InstrumentationCheckApi,
    InstrumentationCheckStatusEnumApi,
} from '../../../generated/api.schemas'

export interface InstrumentationCheckRowProps {
    check: InstrumentationCheckApi
    /** The check whose dismissal or recheck is being saved, if any. */
    pendingCheckKey: AIObservabilityInstrumentationCheckEnumApi | null
    /** Whether the checklist is loading or saving, which holds the other rows' buttons. */
    busy: boolean
    onDismiss: (key: AIObservabilityInstrumentationCheckEnumApi) => void
    onRestore: (key: AIObservabilityInstrumentationCheckEnumApi) => void
}

export const INSTRUMENTATION_BUSY_REASON = 'Wait for the current update to finish'

const STATUS_ICONS: Record<InstrumentationCheckStatusEnumApi, JSX.Element> = {
    [InstrumentationCheckStatusEnumApi.Ok]: <IconCheckCircle className="text-success shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Warning]: <IconWarning className="text-warning shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Pending]: <IconClock className="text-muted shrink-0 mt-0.5" />,
    [InstrumentationCheckStatusEnumApi.Dismissed]: <IconMinusSquare className="text-muted shrink-0 mt-0.5" />,
}

export function InstrumentationCheckRow({
    check,
    pendingCheckKey,
    busy,
    onDismiss,
    onRestore,
}: InstrumentationCheckRowProps): JSX.Element {
    const isWarning = check.status === InstrumentationCheckStatusEnumApi.Warning
    const isDismissed = check.status === InstrumentationCheckStatusEnumApi.Dismissed
    const isWriting = pendingCheckKey === check.key

    return (
        <div className="flex items-start gap-2">
            {STATUS_ICONS[check.status]}
            <div className="flex-1 min-w-0">
                <div className={cn('text-sm font-medium', isDismissed && 'text-muted')}>
                    {check.title}
                    {isDismissed ? (
                        <LemonTag type="muted" size="small" className="ml-2">
                            Not applicable
                        </LemonTag>
                    ) : null}
                </div>
                <div className="text-muted text-sm">
                    {check.detail}{' '}
                    {isWarning ? (
                        <Link to={check.docs_url} target="_blank" targetBlankIcon>
                            Learn more
                        </Link>
                    ) : null}
                </div>
            </div>
            {isWarning || isDismissed ? (
                // pinned: data-attrs feed autocapture, so dashboards and tests find the controls by these values
                <LemonButton
                    type="secondary"
                    size="xsmall"
                    className="shrink-0"
                    loading={isWriting}
                    disabledReason={busy && !isWriting ? INSTRUMENTATION_BUSY_REASON : undefined}
                    onClick={() => (isDismissed ? onRestore(check.key) : onDismiss(check.key))}
                    data-attr={
                        isDismissed
                            ? 'ai-observability-instrumentation-checklist-recheck'
                            : 'ai-observability-instrumentation-checklist-dismiss'
                    }
                >
                    {isDismissed ? 'Recheck' : 'Not applicable'}
                </LemonButton>
            ) : null}
        </div>
    )
}
