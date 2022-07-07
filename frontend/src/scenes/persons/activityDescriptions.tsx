import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import React from 'react'
import { PersonType } from '~/types'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

const personActionsMapping: Record<
    keyof PersonType,
    (item: ActivityLogItem, change?: ActivityChange) => string | JSX.Element | null
> = {
    properties: function onChangedProperty() {
        // These API property changes are asynchronous via the plugin server.
        // So the API doesn't capture changes, as they couldn't be guaranteed.
        // only report here that a certain user has manually edited properties
        return <>edited this person's properties</>
    },
    // fields that are excluded on the backend
    id: () => null,
    uuid: () => null,
    distinct_ids: () => null,
    ['name']: () => null,
    created_at: () => null,
    is_identified: () => null,
}

export function personActivityDescriber(logItem: ActivityLogItem): string | JSX.Element | null {
    if (logItem.scope != 'Person') {
        console.error('person describer received a non-person activity')
        return null
    }

    if (logItem.activity === 'deleted') {
        return <>deleted the person: {logItem.detail.name}</>
    }
    if (logItem.activity === 'updated') {
        let changes: (string | JSX.Element | null)[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // model changes have to have a "field" to be described
            }

            changes = changes.concat(personActionsMapping[change.field](logItem, change))
        }

        if (changes.length) {
            return <SentenceList listParts={changes} />
        }
    }
    if (logItem.activity === 'people_merged_into') {
        if (logItem.detail.merge?.source) {
            return (
                <SentenceList
                    prefix="merged into this person:"
                    listParts={logItem.detail.merge.source.flatMap((di) => (
                        <div className={'highlighted-activity'}>
                            <PersonHeader person={di} />
                        </div>
                    ))}
                />
            )
        }
    }

    if (logItem.activity === 'split_person') {
        const distinctIds: string[] | undefined = logItem.detail.changes?.[0].after?.['distinct_ids']
        if (distinctIds) {
            return (
                <SentenceList
                    prefix="split this person into"
                    listParts={distinctIds.map((di) => (
                        <div key={di} className="highlighted-activity">
                            {di}
                        </div>
                    ))}
                />
            )
        }
    }

    return null
}
