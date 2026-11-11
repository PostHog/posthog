import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import type { BookActivityPerson, BookActivityPersonFirstUse } from '~/queries/schema/schema-general'

import { ProductUsagePersonCard } from '../ProductActivity/ProductUsagePersonCard'

export function AccountProductUsageQualifications({
    people,
    firsts,
    columnKey,
    productLabel,
    total,
    partial = false,
}: {
    people: BookActivityPerson[]
    firsts: BookActivityPersonFirstUse[]
    columnKey: string
    productLabel: string
    total: number
    partial?: boolean
}): JSX.Element {
    const end = dayjs(columnKey).add(1, 'week')
    return (
        <div className="flex flex-col gap-3" data-attr="account-product-usage-qualifications">
            <div className="flex flex-col gap-0.5">
                <span className="font-semibold">{`${productLabel} · ${total} ${total === 1 ? 'user' : 'users'}`}</span>
                <span className="text-xs text-secondary">
                    <span>Week of </span>
                    <TZLabel time={columnKey} formatDate="MMM D" formatTime="" />
                    <span> to </span>
                    <TZLabel
                        time={end.subtract(1, 'day').format('YYYY-MM-DD')}
                        formatDate="MMM D, YYYY"
                        formatTime=""
                    />
                    {partial && <span> (to date)</span>}
                </span>
                <span className="text-xs text-secondary">
                    A user counts after 30 seconds on product pages, one product action or one agent call.
                </span>
            </div>
            {people.map((person) => {
                const firstUse = firsts.find(
                    (first) =>
                        first.row === person.row && first.series === person.series && first.personId === person.personId
                )
                return (
                    <ProductUsagePersonCard
                        key={person.personId}
                        person={person}
                        firstUse={firstUse}
                        isNew={
                            !!firstUse &&
                            firstUse.date >= columnKey.slice(0, 10) &&
                            firstUse.date < end.format('YYYY-MM-DD')
                        }
                    />
                )
            })}
            {total > people.length && (
                <span className="text-xs text-secondary">{`${total - people.length} more users are not shown.`}</span>
            )}
        </div>
    )
}
