import { ActivityLogItem, HumanizedChange } from 'lib/components/ActivityLog/humanizeActivity'
import React from 'react'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'

export function personActivityDescriber(logItem: ActivityLogItem): HumanizedChange {
    if (logItem.scope != 'Person') {
        console.error('person describer received a non-person activity')
        return { description: null }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> deleted the person: {logItem.detail.name}
                </>
            ),
        }
    }
    if (logItem.activity === 'updated') {
        // you can only update a person's properties and only one at a time in the UI
        // These API property changes are asynchronous via the plugin server.
        // So the API doesn't capture changes, as they couldn't be guaranteed.
        // only report here that a certain user has manually edited properties

        return {
            description: (
                <>
                    <strong>{logItem.user.first_name}</strong> edited this person's properties
                </>
            ),
        }
    }
    if (logItem.activity === 'people_merged_into') {
        if (logItem.detail.merge?.source) {
            return {
                description: (
                    <SentenceList
                        prefix={
                            <>
                                <strong>{logItem.user.first_name}</strong> merged people into this person:
                            </>
                        }
                        listParts={logItem.detail.merge.source.flatMap((di) => (
                            <span className={'highlighted-activity'}>
                                <PersonHeader person={di} />
                            </span>
                        ))}
                    />
                ),
            }
        }
    }

    if (logItem.activity === 'split_person') {
        const distinctIds: string[] | undefined = logItem.detail.changes?.[0].after?.['distinct_ids']
        if (distinctIds) {
            return {
                description: (
                    <SentenceList
                        prefix={
                            <>
                                <strong>{logItem.user.first_name}</strong> split this person into:{' '}
                            </>
                        }
                        listParts={distinctIds.map((di) => (
                            <span key={di} className="highlighted-activity">
                                {di}
                            </span>
                        ))}
                    />
                ),
            }
        }
    }

    return { description: null }
}
