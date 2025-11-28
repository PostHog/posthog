import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

export function personActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope != 'Person') {
        console.error('person describer received a non-person activity')
        return { description: null }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted the person:{' '}
                    {logItem.detail.name}
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
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> edited this person's
                    properties
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
                                <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> merged
                            </>
                        }
                        listParts={logItem.detail.merge.source.flatMap((di) => (
                            <span className="highlighted-activity">
                                <PersonDisplay person={di} />
                            </span>
                        ))}
                        suffix="into this person"
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
                                <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> split this
                                person into
                            </>
                        }
                        listParts={distinctIds.map((di) => (
                            <span key={di} className="highlighted-activity">
                                <Link to={urls.personByDistinctId(di)}>{di}</Link>
                            </span>
                        ))}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification)
}
