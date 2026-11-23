import { LemonSkeleton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface BreakdownRow {
    label: string
    count: number
}

export interface BreakdownListProps {
    title: string
    /** Null while loading. Sorted largest first. */
    rows: BreakdownRow[] | null
    emptyText: string
    onSelect?: (label: string) => void
    'data-attr': string
}

export function BreakdownList({
    title,
    rows,
    emptyText,
    onSelect,
    'data-attr': dataAttr,
}: BreakdownListProps): JSX.Element {
    const max = Math.max(1, ...(rows ?? []).map((row) => row.count))

    return (
        <section className="flex min-w-0 flex-col gap-1.5">
            <h4 className="m-0 text-xs font-semibold text-secondary">{title}</h4>
            {rows === null ? (
                <LemonSkeleton repeat={3} className="h-5" />
            ) : rows.length === 0 ? (
                <span className="text-xs text-secondary">{emptyText}</span>
            ) : (
                <ul className="m-0 flex list-none flex-col gap-1 p-0">
                    {rows.map((row) => {
                        const bar = (
                            <>
                                <span
                                    className="absolute inset-y-0 left-0 rounded-sm bg-fill-highlight-100"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: `${(row.count / max) * 100}%` }}
                                />
                                <span className="relative min-w-0 flex-1 truncate font-mono">{row.label}</span>
                                <span className="relative tabular-nums text-secondary">
                                    {humanFriendlyNumber(row.count)}
                                </span>
                            </>
                        )
                        const className =
                            'relative flex w-full items-center gap-2 rounded-sm px-1.5 py-0.5 text-left text-xs'
                        return (
                            <li key={row.label} className="ph-no-capture">
                                {onSelect ? (
                                    <button
                                        type="button"
                                        className={`${className} cursor-pointer hover:bg-fill-highlight-50`}
                                        onClick={() => onSelect(row.label)}
                                        data-attr={dataAttr}
                                    >
                                        {bar}
                                    </button>
                                ) : (
                                    <div className={className}>{bar}</div>
                                )}
                            </li>
                        )
                    })}
                </ul>
            )}
        </section>
    )
}
