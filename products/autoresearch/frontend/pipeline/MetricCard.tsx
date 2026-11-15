import { Tooltip } from '@posthog/lemon-ui'

export function MetricCard({
    label,
    value,
    detail,
    tooltip,
}: {
    label: string
    value: string
    detail?: string
    tooltip?: string
}): JSX.Element {
    const labelElement = (
        <div className={`text-xs font-semibold text-muted uppercase tracking-wide${tooltip ? ' cursor-help' : ''}`}>
            {label}
        </div>
    )
    return (
        <div className="rounded bg-surface-secondary p-3 space-y-1">
            {tooltip ? <Tooltip title={tooltip}>{labelElement}</Tooltip> : labelElement}
            <div className="text-lg font-bold truncate">{value}</div>
            {detail && <div className="text-xs text-secondary">{detail}</div>}
        </div>
    )
}
