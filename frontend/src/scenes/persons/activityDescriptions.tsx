import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import React from 'react'
import { PersonType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PersonHeader } from 'scenes/persons/PersonHeader'

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
        // there should always and only be one... but it depends how often the API is used to patch Persons
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

export function personActivityDescriber(logItem: ActivityLogItem): (string | JSX.Element | null)[] {
    if (logItem.scope != 'Person') {
        return [] // currently, only humanizes the feature flag scope
    }
    const descriptions = []
    if (logItem.activity === 'deleted') {
        descriptions.push(<>deleted the person: {logItem.detail.name}</>)
    }
    if (logItem.activity === 'updated') {
        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue // model changes have to have a "field" to be described
            }

            descriptions.push(personActionsMapping[change.field](logItem, change))
        }
    }
    if (logItem.activity === 'people_merged_into') {
        if (logItem.detail.merge?.source) {
            descriptions.push(<ListPeople datasource={logItem.detail.merge.source} label="merged into this person: " />)
        }
    }

    if (logItem.activity === 'split_person') {
        const distinctIds: string[] | undefined = logItem.detail.changes?.[0].after?.['distinct_ids']
        if (distinctIds) {
            descriptions.push(<ListPeople datasource={distinctIds} label="split this person into" />)
        }
    }
    return descriptions
}

function ListPeople({ datasource, label }: { datasource: (string | PersonType)[]; label: string }): JSX.Element {
    return (
        <div className="people-list">
            <div>{label}&nbsp;</div>
            {datasource?.flatMap((di, index) => {
                const numberOfPeopleMerged = datasource?.length || 0
                const isntFirst = index > 0
                const isLast = index === numberOfPeopleMerged - 1
                return [
                    isntFirst && <div>,&nbsp;</div>,
                    isLast && datasource.length >= 2 && <div>and&nbsp;</div>,
                    <div key={index} className={'highlighted-info'}>
                        {typeof di === 'string' ? di : <PersonHeader person={di} />}
                    </div>,
                ]
            })}
        </div>
    )
}
