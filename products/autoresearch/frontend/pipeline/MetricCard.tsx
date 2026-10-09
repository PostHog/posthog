import { Tooltip } from '@posthog/lemon-ui'

export function MetricCard({ label, value, tooltip }: { label: string; value: string; tooltip?: string }): JSX.Element {
    const labelElement = (
        <div className={`text-xs font-semibold text-muted uppercase tracking-wide${tooltip ? ' cursor-help' : ''}`}>
            {label}
        </div>
    )
    return (
        <div className="border rounded p-3 space-y-1">
            {tooltip ? <Tooltip title={tooltip}>{labelElement}</Tooltip> : labelElement}
            <div className="text-lg font-bold truncate">{value}</div>
        </div>
    )
}
