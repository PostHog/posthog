import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import React from 'react'
import { PersonType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { SentenceList } from 'scenes/feature-flags/activityDescriptions'

type personFields = keyof PersonType

const isRecord = (candidate?: string | Record<string, any> | boolean): candidate is Record<string, any> =>
    typeof candidate === 'object'

const personActionsMapping: {
    [field in personFields]: (item: ActivityLogItem, change?: ActivityChange) => string | JSX.Element | null
} = {
    properties: function onChangedProperty(_, change) {
        const before = change?.before
        const after = change?.after

        if (!after || !isRecord(after)) {
            // must always have an after which is a record
            return null
        }

        // UI only lets you add properties one at a time,
        // so this can return the first changed property
        // there should always and only be one... but it depends on how often the API is used to patch Persons
        const changedProperties = Object.keys(after).filter((key) => isRecord(before) && !(key in before))
        if (changedProperties[0]) {
            return (
                <>
                    added property{' '}
                    <strong>
                        <PropertyKeyInfo value={changedProperties[0]} />
                    </strong>{' '}
                    with value:{' '}
                    <strong>
                        {after[changedProperties[0]] === null ? 'null' : String(after[changedProperties[0]])}
                    </strong>
                </>
            )
        }

        return null
    },
    // fields that shouldn't show in the log if they change
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
