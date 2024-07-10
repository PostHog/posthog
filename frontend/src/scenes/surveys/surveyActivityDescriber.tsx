import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    defaultDescriber,
    Description,
    detectBoolean,
    HumanizedChange,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

const nameOrLinkToSurvey = (id: string | undefined, name: string | null | undefined): string | JSX.Element => {
    const displayName = name || '(empty string)'
    return id ? <Link to={urls.survey(id)}>{displayName}</Link> : displayName
}

const surveyActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    name: function onName() {
        return {
            description: [<>changed the name</>],
        }
    },
    description: function onDescription() {
        return {
            description: [<>updated the description</>],
        }
    },
    type: function onType(change) {
        return {
            description: [
                <>
                    changed the survey type to <span className="highlighted-activity">{change?.after as string}</span>
                </>,
            ],
        }
    },
    questions: function onQuestions() {
        return {
            description: [<>updated the survey questions</>],
        }
    },
    active: function onActive(change) {
        const isActive = detectBoolean(change?.after)
        const describeChange: string = isActive ? 'activated' : 'deactivated'
        return {
            description: [<>{describeChange} the survey</>],
        }
    },
}

export function surveyActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Survey') {
        console.error('survey describer received a non-survey activity')
        return { description: null }
    }

    if (logItem.activity === 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = (
            <>
                on {asNotification && ' the survey '}
                {nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name)}
            </>
        )

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue
            }

            const possibleLogItem = surveyActionsMapping[change.field]?.(change, logItem)
            if (possibleLogItem) {
                const { description, suffix } = possibleLogItem
                if (description) {
                    changes = changes.concat(description)
                }
                if (suffix) {
                    changeSuffix = suffix
                }
            }
        }

        if (changes.length) {
            return {
                description: (
                    <SentenceList
                        listParts={changes}
                        prefix={
                            <>
                                <strong>{userNameForLogItem(logItem)}</strong>
                            </>
                        }
                        suffix={changeSuffix}
                    />
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name))
}
