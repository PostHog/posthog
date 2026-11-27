import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { TraceCellStatus } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'

const COUNT_FAILED = "Couldn't load this count. Reload the list to try again."

export interface QuickFilterChip {
    id: string
    label: string
    count: number | null
    /** A count read apart from the list passes its status. A count the list carries is always ready. */
    countStatus?: TraceCellStatus
    tone?: 'danger' | 'default'
}

function ChipCount({
    count,
    countStatus = 'ready',
}: Pick<QuickFilterChip, 'count' | 'countStatus'>): JSX.Element | null {
    if (countStatus !== 'ready') {
        return (
            <span className="ml-1.5 inline-flex">
                <TraceCellValue status={countStatus} skeletonWidth="w-4" failedMessage={COUNT_FAILED}>
                    {null}
                </TraceCellValue>
            </span>
        )
    }
    return count !== null ? (
        <span className="ml-1.5 text-secondary tabular-nums">{humanFriendlyNumber(count)}</span>
    ) : null
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
                    <ChipCount count={chip.count} countStatus={chip.countStatus} />
                </LemonButton>
            ))}
        </div>
    )
}
