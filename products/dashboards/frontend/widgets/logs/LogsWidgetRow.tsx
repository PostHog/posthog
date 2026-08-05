import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import type { LogMessage } from '~/queries/schema/schema-general'

import { SEVERITY_BAR_COLORS } from 'products/logs/frontend/components/VirtualizedLogsList/columnDefinitions'

export type LogsWidgetLogLine = {
    uuid: string
    timestamp: string
    /** OTel severity text, e.g. "info", "error". `level` is the same value (runner aliases it). */
    severity_text?: string | null
    level?: string | null
    body: string
    trace_id?: string | null
}

function severityKey(line: LogsWidgetLogLine): string {
    return (line.severity_text ?? line.level ?? '').toLowerCase()
}

function severityLabel(line: LogsWidgetLogLine): string {
    return (line.severity_text ?? line.level ?? 'log').toUpperCase()
}

/** Reuse the logs viewer's severity bar colors so a row reads the same as on the logs page. */
function severityBarClass(line: LogsWidgetLogLine): string {
    return SEVERITY_BAR_COLORS[severityKey(line) as LogMessage['severity_text']] ?? 'bg-muted-3000'
}

export function LogsWidgetRowSkeleton(): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-3 py-1.5">
            <LemonSkeleton className="h-4 w-1 shrink-0 rounded-full" />
            <LemonSkeleton className="h-3 w-32 shrink-0" />
            <LemonSkeleton className="h-3 flex-1" />
        </div>
    )
}

export function LogsWidgetRow({
    line,
    wrapLines = false,
    displayTimezone,
    href,
}: {
    line: LogsWidgetLogLine
    wrapLines?: boolean
    displayTimezone?: string
    href?: string
}): JSX.Element {
    const content = (
        <div
            className={cn(
                'group flex gap-2 px-3 py-1.5 hover:bg-fill-highlight-100',
                wrapLines ? 'items-start' : 'items-center'
            )}
            data-attr="logs-widget-row"
        >
            <Tooltip title={severityLabel(line)}>
                <div
                    aria-label={severityLabel(line)}
                    className={cn('w-1 shrink-0 self-stretch rounded-full', severityBarClass(line))}
                />
            </Tooltip>
            <span className="shrink-0 font-mono text-xs text-muted">
                <TZLabel
                    time={line.timestamp}
                    formatDate="YYYY-MM-DD"
                    formatTime="HH:mm:ss.SSS"
                    displayTimezone={displayTimezone}
                    timestampStyle="absolute"
                    showPopover={false}
                />
            </span>
            <span
                className={cn(
                    'min-w-0 flex-1 font-mono text-xs text-primary',
                    wrapLines ? 'whitespace-pre-wrap break-all' : 'truncate'
                )}
                title={wrapLines ? undefined : line.body}
            >
                {line.body}
            </span>
        </div>
    )

    if (href) {
        return (
            <Link to={href} target="_blank" className="block text-current hover:text-current" subtle>
                {content}
            </Link>
        )
    }

    return content
}
