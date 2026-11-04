import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { BookActivityPerson, BookActivityPersonFirstUse } from '~/queries/schema/schema-general'

import { ProductUsagePersonTooltip } from '../ProductUsageGrid/ProductUsagePersonTooltip'

export function AccountProductUsagePeople({
    people,
    firsts,
    total,
    columnKey,
    showDetails = false,
}: {
    people: BookActivityPerson[]
    firsts: BookActivityPersonFirstUse[]
    total: number
    columnKey: string
    showDetails?: boolean
}): JSX.Element {
    const end = dayjs(columnKey).add(1, 'week').format('YYYY-MM-DD')
    const period = <div className="mb-2 text-secondary">Week of {dayjs(columnKey).format('MMM D, YYYY')}</div>
    return (
        <div className={showDetails ? 'flex flex-col gap-3 text-xs' : 'flex flex-wrap items-center gap-x-1 text-xs'}>
            {showDetails && period}
            {people.map((person, index) => {
                const firstUse = firsts.find(
                    (first) =>
                        first.row === person.row && first.series === person.series && first.personId === person.personId
                )
                const details = (
                    <ProductUsagePersonTooltip
                        person={person}
                        firstUse={firstUse}
                        isNew={!!firstUse && firstUse.date >= columnKey.slice(0, 10) && firstUse.date < end}
                    />
                )
                return showDetails ? (
                    <div key={person.personId}>{details}</div>
                ) : (
                    <Tooltip
                        key={person.personId}
                        title={
                            <>
                                {period}
                                {details}
                            </>
                        }
                    >
                        <span tabIndex={0} className="max-w-full truncate">
                            <span>{person.label}</span>
                            {index < people.length - 1 && <span>,</span>}
                        </span>
                    </Tooltip>
                )
            })}
            {total > people.length && <span className="text-secondary">{`+${total - people.length} more`}</span>}
            {!people.length && total === 0 && <span className="text-secondary">No activity</span>}
        </div>
    )
}
