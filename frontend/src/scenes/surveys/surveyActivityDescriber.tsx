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

const nameOrLinkToSurvey = (
    id: string | undefined,
    name: string | null | undefined,
    activity: string
): string | JSX.Element => {
    const displayName = name || '(empty string)'
    if (activity === 'deleted') {
        // Don't show a link to a deleted survey, since the user can't view it
        return <strong>{displayName}</strong>
    }
    return id ? <Link to={urls.survey(id)}>{displayName}</Link> : displayName
}

const surveyActionsMapping: Record<
    string,
    (change?: ActivityChange, logItem?: ActivityLogItem) => ChangeMapping | null
> = {
    name: function onName() {
        return {
            description: [<>changed the name of survey:</>],
        }
    },
    description: function onDescription() {
        return {
            description: [<>updated the description of survey:</>],
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
            description: [<>updated the questions of survey:</>],
        }
    },
    archived: function onArchived(change) {
        const isArchived = detectBoolean(change?.after)
        const describeChange: string = isArchived ? 'archived' : 'unarchived'
        return {
            description: [<>{describeChange}</>],
        }
    },
    start_date: function onStartDate(change) {
        if (change?.before === null && change?.after !== null) {
            return {
                description: [<>launched survey:</>],
            }
        }
        return null
    },
    end_date: function onEndDate(change) {
        if (change?.before === null && change?.after !== null) {
            return {
                description: [<>stopped survey:</>],
            }
        }
        return null
    },
    appearance: function onAppearance() {
        return {
            description: [<>customized the appearance of survey:</>],
        }
    },
    conditions: function onConditions() {
        return {
            description: [<>modified the display conditions of survey:</>],
        }
    },
    responses_limit: function onResponsesLimit() {
        return {
            description: [<>modified the completion conditions of survey:</>],
        }
    },
}

export function surveyActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Survey') {
        console.error('survey describer received a non-survey activity')
        return { description: null }
    }

    if (logItem.activity === 'created') {
        return {
            description: (
                <SentenceList
                    listParts={[<>created a new survey:</>]}
                    prefix={
                        <>
                            <strong>{userNameForLogItem(logItem)}</strong>
                        </>
                    }
                    suffix={
                        <>
                            <strong>
                                {nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name, logItem.activity)}
                            </strong>
                        </>
                    }
                />
            ),
        }
    }

    if (logItem.activity === 'updated') {
        let changes: Description[] = []
        let changeSuffix: Description = (
            <>
                {asNotification && ' the survey '}
                <strong>{nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name, logItem.activity)}</strong>
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

    return defaultDescriber(
        logItem,
        asNotification,
        nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name, logItem.activity)
    )
}
