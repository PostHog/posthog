import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { BookActivityPerson, BookActivityPersonFirstUse } from '~/queries/schema/schema-general'

import { getProductUsagePersonSummary } from './productUsagePresentation'

export function ProductUsagePersonTooltip({
    person,
    firstUse,
    isNew,
}: {
    person: BookActivityPerson
    firstUse?: BookActivityPersonFirstUse
    isNew: boolean
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2 max-w-80">
            <strong className="break-all">{person.label}</strong>
            {firstUse && (
                <div className={isNew ? 'text-accent' : undefined}>
                    <span>First use: </span>
                    <TZLabel time={firstUse.date} formatDate="MMM D, YYYY" />
                </div>
            )}
            <span>{getProductUsagePersonSummary(person, humanFriendlyDuration)}</span>
            {person.actions.map((action) => (
                <span key={action.event}>{`${action.event}: ${action.count}`}</span>
            ))}
            {person.topPaths.length > 0 && (
                <div className="flex flex-col gap-1">
                    <strong>Top pages</strong>
                    {person.topPaths.map((path) => (
                        <span
                            className="break-all"
                            key={path.path}
                        >{`${path.path}: ${Math.round(path.seconds)} seconds`}</span>
                    ))}
                </div>
            )}
        </div>
    )
}
