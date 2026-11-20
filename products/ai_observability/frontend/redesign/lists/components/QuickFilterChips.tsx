import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

export interface QuickFilterChip {
    id: string
    label: string
    count: number | null
    tone?: 'danger' | 'default'
}

export interface QuickFilterChipsProps {
    chips: QuickFilterChip[]
    active: string | null
    onToggle: (id: string) => void
    'data-attr': string
}

export function QuickFilterChips({
    chips,
    active,
    onToggle,
    'data-attr': dataAttr,
}: QuickFilterChipsProps): JSX.Element {
    return (
        <div className="flex flex-wrap items-center gap-2">
            {chips.map((chip) => (
                <LemonButton
                    key={chip.id}
                    type="secondary"
                    size="small"
                    active={chip.id === active}
                    aria-pressed={chip.id === active}
                    icon={chip.tone === 'danger' ? <span className="size-2 rounded-full bg-danger" /> : undefined}
                    onClick={() => onToggle(chip.id)}
                    // pinned: autocapture dashboards and tests select the chips by this value
                    data-attr={`${dataAttr}-quick-filter-${chip.id}`}
                >
                    {chip.label}
                    {chip.count !== null ? (
                        <span className="ml-1.5 text-secondary tabular-nums">{humanFriendlyNumber(chip.count)}</span>
                    ) : null}
                </LemonButton>
            ))}
        </div>
    )
}
