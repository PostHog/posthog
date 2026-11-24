export interface WarehouseMeterProps {
    used: number
    /** The allowance or budget the meter compares against. */
    limit: number
    /** `budget`: going over the limit is a problem, so the fill turns danger. Otherwise it stays accent. */
    tone?: 'allowance' | 'budget'
    label: string
}

/**
 * Past an allowance is normal use, so the fill never turns red for it. Over the limit the bar fills
 * and a small tick marks where the allowance ends. Only a budget that is exceeded uses the danger color.
 */
export function WarehouseMeter({ used, limit, tone = 'allowance', label }: WarehouseMeterProps): JSX.Element {
    const scale = Math.max(used, limit, 1)
    const over = limit > 0 && used > limit
    const fillPercent = Math.min(100, (used / scale) * 100)
    const tickPercent = (limit / scale) * 100
    const danger = tone === 'budget' && over

    return (
        <div
            role="meter"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={limit}
            aria-valuenow={Math.min(used, limit)}
            className="relative h-1.5 w-full rounded-full bg-[var(--input)]"
        >
            <div
                className={`h-full rounded-full ${danger ? 'bg-[var(--destructive-foreground)]' : 'bg-[var(--info-foreground)]'}`}
                style={{ width: `${fillPercent}%` }}
            />
            {over ? (
                <div
                    className="absolute -top-0.5 h-2.5 w-0.5 rounded-full bg-[var(--foreground)]"
                    style={{ left: `calc(${tickPercent}% - 1px)` }}
                    aria-hidden
                />
            ) : null}
        </div>
    )
}
