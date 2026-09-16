// Change fragments that several activity describers share, for fields more than
// one scope can change (tags, description).
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { pluralize } from 'lib/utils/strings'

import { ActivityChange, ChangeMapping, Description } from '../humanizeActivity'

/** Describes added/removed string lists rendered as inline tags, e.g. tags or evaluation contexts. */
export function describeListChanges(
    change: ActivityChange | undefined,
    singular: string,
    plural: string
): ChangeMapping {
    const before = (change?.before as string[] | null) ?? []
    const after = (change?.after as string[] | null) ?? []
    const added = after.filter((t) => before.indexOf(t) === -1)
    const removed = before.filter((t) => after.indexOf(t) === -1)

    const changes: Description[] = []
    if (added.length) {
        changes.push(
            <>
                added {pluralize(added.length, singular, plural, false)}{' '}
                <ObjectTags tags={added} saving={false} style={{ display: 'inline' }} staticOnly />
            </>
        )
    }
    if (removed.length) {
        changes.push(
            <>
                removed {pluralize(removed.length, singular, plural, false)}{' '}
                <ObjectTags tags={removed} saving={false} style={{ display: 'inline' }} staticOnly />
            </>
        )
    }

    return { description: changes }
}

export function describeTagChanges(change?: ActivityChange): ChangeMapping {
    return describeListChanges(change, 'tag', 'tags')
}

export function describeDescriptionChange(
    change: ActivityChange | undefined,
    asNotification: boolean | undefined,
    scopeNoun: string
): Description[] {
    return [
        <>
            changed the description {asNotification && ` of the ${scopeNoun} `}to{' '}
            <strong>"{change?.after as string}"</strong>
        </>,
    ]
}
