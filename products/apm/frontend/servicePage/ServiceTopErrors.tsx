import { LemonBanner, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    TRACING_DATE_FORMAT,
    TRACING_DISPLAY_TIMEZONE,
    TRACING_TIME_FORMAT,
} from 'products/tracing/frontend/dateFormats'

import type { StatusCodeErrors, TopError } from './servicePage'

export interface ServiceTopErrorsProps {
    topErrors: TopError[]
    topErrorsLoading: boolean
    sampleSize: number
    sampleLimit: number
    statusCodeErrors: StatusCodeErrors[]
    /** The last error-span or status-code fetch failed, so the section would show stale or missing rows as current. */
    failed: boolean
    onRetry: () => void
}

export function ServiceTopErrors({
    topErrors,
    topErrorsLoading,
    sampleSize,
    sampleLimit,
    statusCodeErrors,
    failed,
    onRetry,
}: ServiceTopErrorsProps): JSX.Element {
    if (failed && !topErrorsLoading) {
        return (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: () => onRetry() }}>
                Couldn't load this service's errors.
            </LemonBanner>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            {statusCodeErrors.length > 0 && (
                <div className="flex flex-wrap items-center gap-2" data-attr="apm-service-status-code-errors">
                    <span className="text-xs text-muted">Errors by HTTP status</span>
                    {statusCodeErrors.map(({ statusCode, errors }) => (
                        <LemonTag key={statusCode} type="danger" size="small">
                            <span className="font-mono">{statusCode}</span>
                            <span>·</span>
                            <span>{humanFriendlyNumber(errors)}</span>
                        </LemonTag>
                    ))}
                </div>
            )}
            <LemonTable<TopError>
                dataSource={topErrors}
                loading={topErrorsLoading}
                rowKey="message"
                size="small"
                emptyState="No errors in this window"
                columns={[
                    {
                        title: 'Error message',
                        key: 'message',
                        render: (_, row) => (
                            <span className="ph-replay-block ph-no-capture font-mono break-all">{row.message}</span>
                        ),
                    },
                    {
                        title: 'Spans',
                        key: 'count',
                        align: 'right',
                        render: (_, row) => humanFriendlyNumber(row.count),
                    },
                    {
                        title: 'Last seen',
                        key: 'lastSeen',
                        render: (_, row) => (
                            <TZLabel
                                time={row.lastSeen}
                                formatDate={TRACING_DATE_FORMAT}
                                formatTime={TRACING_TIME_FORMAT}
                                displayTimezone={TRACING_DISPLAY_TIMEZONE}
                            />
                        ),
                    },
                    {
                        title: 'Latest trace',
                        key: 'latest',
                        render: (_, row) => (
                            <Link
                                to={traceUrl({
                                    traceId: row.latest.trace_id,
                                    spanId: row.latest.span_id,
                                    ts: row.latest.timestamp,
                                })}
                                data-attr="apm-service-error-trace-link"
                            >
                                View trace
                            </Link>
                        ),
                    },
                ]}
            />
            {sampleSize > 0 && (
                <span className="text-xs text-muted">
                    <span>Grouped from the most recent error spans: </span>
                    <span translate="no">{humanFriendlyNumber(sampleSize)}</span>
                    {sampleSize >= sampleLimit ? <span>. Older errors are not counted.</span> : null}
                </span>
            )}
        </div>
    )
}
