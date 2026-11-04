import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { BookActivityPerson } from '~/queries/schema/schema-general'

export function AccountProductUsagePeople({
    people,
    total,
    columnKey,
    productLabel,
    partial = false,
    showDetails = false,
    onInspect,
}: {
    people: BookActivityPerson[]
    total: number
    columnKey: string
    productLabel?: string
    partial?: boolean
    showDetails?: boolean
    onInspect?: () => void
}): JSX.Element {
    const end = dayjs(columnKey).add(1, 'week')
    if (!showDetails) {
        const names = people.map((person) => person.label).join(', ')
        const remaining = total - people.length
        return (
            <Tooltip
                interactive
                title={
                    <AccountProductUsagePeople
                        people={people}
                        total={total}
                        columnKey={columnKey}
                        productLabel={productLabel}
                        partial={partial}
                        showDetails
                        onInspect={onInspect}
                    />
                }
            >
                <span
                    tabIndex={0}
                    className="block max-w-full truncate text-xs"
                    data-attr="account-product-usage-top-users"
                >
                    {names ? `${names}${remaining > 0 ? ` +${remaining}` : ''}` : 'No activity'}
                </span>
            </Tooltip>
        )
    }
    return (
        <div className="flex flex-col gap-2 text-xs w-72 max-w-full" data-attr="account-product-usage-weekly-summary">
            <strong>{`${productLabel ?? 'Product activity'} · ${total} ${total === 1 ? 'user' : 'users'}`}</strong>
            <div className="text-secondary">
                <span>Week of </span>
                <TZLabel time={columnKey} formatDate="MMM D" formatTime="" />
                <span> to </span>
                <TZLabel time={end.subtract(1, 'day').format('YYYY-MM-DD')} formatDate="MMM D, YYYY" formatTime="" />
                {partial && <span> (to date)</span>}
            </div>
            {people.map((person) => (
                <div key={person.personId} className="flex items-baseline justify-between gap-3">
                    <span className="truncate" title={person.label}>
                        {person.label}
                    </span>
                    <span className="shrink-0 text-secondary">{`${humanFriendlyDuration(person.engagedSeconds)} · ${person.actionCount} ${person.actionCount === 1 ? 'action' : 'actions'}`}</span>
                </div>
            ))}
            {total > people.length && <span className="text-secondary">{`+${total - people.length} more`}</span>}
            {!people.length && total === 0 && <span className="text-secondary">No activity</span>}
            {people.length > 0 && onInspect && (
                <LemonButton size="xsmall" type="secondary" onClick={onInspect}>
                    Qualification details
                </LemonButton>
            )}
        </div>
    )
}
