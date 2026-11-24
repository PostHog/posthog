import type { ReactNode } from 'react'

/** One number in a drawer's row of stats, with its label above and a line of context below. */
export function EvaluationDrawerStat({
    label,
    value,
    detail,
}: {
    label: string
    value: string
    detail?: ReactNode
}): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col rounded border border-primary px-3 py-2">
            <span className="text-xs text-secondary">{label}</span>
            <span className="text-base font-semibold tabular-nums">{value}</span>
            {detail ? <span className="truncate text-xs text-secondary">{detail}</span> : null}
        </div>
    )
}
