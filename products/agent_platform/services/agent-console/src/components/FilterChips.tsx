/**
 * `<FilterChips />` — segmented pill control for list filters.
 *
 * Designed for the agent list (`all / live / drafts / archived`) but
 * generic over the options array. Adopted from the command-center's
 * filter pattern; tuned for our minimal style (no uppercase, no heavy
 * borders).
 */

export interface FilterChipsProps<T extends string> {
    options: readonly T[]
    value: T
    onChange: (next: T) => void
    /** Optional labels per option; falls back to the value with sentence case. */
    labels?: Partial<Record<T, string>>
    className?: string
}

export function FilterChips<T extends string>({
    options,
    value,
    onChange,
    labels,
    className,
}: FilterChipsProps<T>): React.ReactElement {
    return (
        <div
            className={
                'inline-flex overflow-hidden rounded-md border border-border bg-card' +
                (className ? ` ${className}` : '')
            }
            role="group"
            aria-label="Filter"
        >
            {options.map((opt, i) => {
                const label = labels?.[opt] ?? humanize(opt)
                const isActive = value === opt
                return (
                    <button
                        key={opt}
                        type="button"
                        onClick={() => onChange(opt)}
                        aria-pressed={isActive}
                        className={
                            (isActive
                                ? 'bg-primary text-primary-foreground shadow-sm'
                                : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground') +
                            ' cursor-pointer px-2.5 py-1 text-xs font-medium transition-colors' +
                            (i > 0 ? ' border-l border-border' : '')
                        }
                    >
                        {label}
                    </button>
                )
            })}
        </div>
    )
}

function humanize(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1).replace(/-/g, ' ')
}
