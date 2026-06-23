import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

export type LogsWidgetLogLine = {
    uuid: string
    timestamp: string
    /** OTel severity text, e.g. "info", "error". `level` is the same value (runner aliases it). */
    severity_text?: string | null
    level?: string | null
    body: string
    trace_id?: string | null
}

/** Tailwind chip colors per severity bucket; unknown levels fall back to a neutral chip. */
const SEVERITY_CHIP_CLASSES: Record<string, string> = {
    trace: 'bg-surface-secondary text-muted',
    debug: 'bg-surface-secondary text-muted',
    info: 'bg-primary-highlight text-primary',
    warn: 'bg-warning-highlight text-warning',
    error: 'bg-danger-highlight text-danger',
    fatal: 'bg-danger-highlight text-danger',
}

function severityLabel(line: LogsWidgetLogLine): string {
    return (line.severity_text ?? line.level ?? 'log').toUpperCase()
}

function severityChipClass(line: LogsWidgetLogLine): string {
    const key = (line.severity_text ?? line.level ?? '').toLowerCase()
    return SEVERITY_CHIP_CLASSES[key] ?? 'bg-surface-secondary text-muted'
}

export function LogsWidgetRowSkeleton(): JSX.Element {
    return (
        <div className="flex items-center gap-2 px-3 py-2">
            <LemonSkeleton className="h-4 w-12 shrink-0 rounded" />
            <LemonSkeleton className="h-4 flex-1" />
            <LemonSkeleton className="h-3 w-20 shrink-0" />
        </div>
    )
}

export function LogsWidgetRow({ line }: { line: LogsWidgetLogLine }): JSX.Element {
    return (
        <div
            className="@container flex items-center gap-2 px-3 py-2 hover:bg-surface-secondary"
            data-attr="logs-widget-row"
        >
            <span
                className={`shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase ${severityChipClass(
                    line
                )}`}
            >
                {severityLabel(line)}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-primary" title={line.body}>
                {line.body}
            </span>
            <span className="w-20 shrink-0 truncate text-right text-xs text-muted">
                <TZLabel time={line.timestamp} />
            </span>
        </div>
    )
}
