import { LemonButton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import type {
    BookActivityInterval,
    BookActivityPerson,
    BookActivityPersonFirstUse,
} from '~/queries/schema/schema-general'

import { ProductUsagePersonTooltip } from './ProductUsagePersonTooltip'

export function ProductUsageNamesCell({
    people,
    total,
    firstUse,
    columnKey,
    interval,
    expanded,
    loading,
    onToggle,
}: {
    people: BookActivityPerson[]
    total: number
    firstUse: BookActivityPersonFirstUse[]
    columnKey: string
    interval: BookActivityInterval
    expanded: boolean
    loading?: boolean
    onToggle: () => void
}): JSX.Element {
    if (loading && !people.length) {
        return <Spinner />
    }
    return (
        <div className="flex flex-col items-start gap-1 min-w-24 max-w-40">
            {people.map((person) => {
                const first = firstUse.find(
                    (item) =>
                        item.row === person.row && item.series === person.series && item.personId === person.personId
                )
                const date = first && dayjs(first.date)
                const isNew =
                    !!date &&
                    !date.isBefore(dayjs(columnKey), 'day') &&
                    date.isBefore(dayjs(columnKey).add(1, interval), 'day')
                return (
                    <Tooltip
                        key={person.personId}
                        title={<ProductUsagePersonTooltip person={person} firstUse={first} isNew={isNew} />}
                    >
                        <span className="flex items-center gap-1 max-w-full">
                            <span className="truncate" tabIndex={0}>
                                {person.label}
                            </span>
                            {isNew && (
                                <LemonTag type="highlight" size="small">
                                    New
                                </LemonTag>
                            )}
                        </span>
                    </Tooltip>
                )
            })}
            {!people.length && !loading && <span className="text-tertiary">·</span>}
            {(expanded || total > people.length) && (
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    onClick={onToggle}
                    loading={loading}
                    data-attr="product-activity-more-people"
                >
                    {expanded ? 'Show less' : `+${total - people.length} more`}
                </LemonButton>
            )}
        </div>
    )
}
