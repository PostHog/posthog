import { dayjs } from 'lib/dayjs'

import type { BookActivityPerson, BookActivityPersonFirstUse } from '~/queries/schema/schema-general'

import { ProductUsagePersonTooltip } from '../ProductUsageGrid/ProductUsagePersonTooltip'

export function AccountProductUsageQualifications({
    people,
    firsts,
    columnKey,
}: {
    people: BookActivityPerson[]
    firsts: BookActivityPersonFirstUse[]
    columnKey: string
}): JSX.Element {
    const end = dayjs(columnKey).add(1, 'week').format('YYYY-MM-DD')
    return (
        <div className="flex flex-col gap-4">
            {people.map((person) => {
                const firstUse = firsts.find(
                    (first) =>
                        first.row === person.row && first.series === person.series && first.personId === person.personId
                )
                return (
                    <ProductUsagePersonTooltip
                        key={person.personId}
                        person={person}
                        firstUse={firstUse}
                        isNew={!!firstUse && firstUse.date >= columnKey.slice(0, 10) && firstUse.date < end}
                    />
                )
            })}
        </div>
    )
}
