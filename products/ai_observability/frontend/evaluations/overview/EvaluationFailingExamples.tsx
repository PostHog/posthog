import { Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import type { EvaluationRunApi } from '../../generated/api.schemas'

export function EvaluationFailingExamples({ failures }: { failures: EvaluationRunApi[] }): JSX.Element {
    return (
        <ul className="flex flex-col gap-3">
            {failures.map((failure, index) => (
                <li key={`${failure.timestamp}-${index}`} className="flex items-start justify-between gap-2 min-w-0">
                    <div className="flex flex-col gap-0.5 min-w-0">
                        <span className={cn('text-sm line-clamp-3', !failure.reasoning && 'text-secondary')}>
                            {failure.reasoning ?? 'No reasoning was recorded for this result.'}
                        </span>
                        {/* noStyles drops the dotted underline, which read as a second separator under each item. */}
                        <TZLabel time={failure.timestamp} noStyles className="text-xs text-secondary" />
                    </div>
                    {failure.traceId && (
                        <Link
                            // The result is recorded after the trace ends, and the trace view reads a timestamp as
                            // the trace's earliest event, so passing it would hide the trace.
                            to={urls.aiObservabilityTrace(
                                failure.traceId,
                                failure.targetEventId ? { event: failure.targetEventId } : undefined
                            )}
                            className="text-xs shrink-0"
                            data-attr="evaluation-overview-drawer-trace"
                        >
                            View trace
                        </Link>
                    )}
                </li>
            ))}
        </ul>
    )
}
