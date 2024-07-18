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
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { Survey, SurveyAppearance } from '~/types'

const isEmptyOrUndefined = (value: any): boolean => value === undefined || value === null || value === ''

const nameOrLinkToSurvey = (
    id: string | undefined,
    name: string | null | undefined,
    activity: string
): string | JSX.Element => {
    const displayName = name || '(empty string)'
    if (activity === 'deleted') {
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
                    changed the type to <strong>{change?.after as string}</strong>
                </>,
            ],
        }
    },
    questions: function onQuestions() {
        return {
            description: [<>updated the questions</>],
        }
    },
    archived: function onArchived(change) {
        const isArchived = detectBoolean(change?.after)
        return {
            description: [isArchived ? <>archived</> : <>unarchived</>],
        }
    },
    start_date: function onStartDate(change) {
        if (change?.before === null && change?.after !== null) {
            return {
                description: [<>launched</>],
            }
        }
        return null
    },
    end_date: function onEndDate(change) {
        if (change?.before === null && change?.after !== null) {
            return {
                description: [<>stopped</>],
            }
        }
        return null
    },
    appearance: function onAppearance(change) {
        const beforeAppearance = change?.before as SurveyAppearance
        const afterAppearance = change?.after as SurveyAppearance
        const changes: JSX.Element[] = []

        const fieldNameMapping: Record<keyof SurveyAppearance, string> = {
            backgroundColor: 'background color',
            submitButtonColor: 'submit button color',
            submitButtonText: 'submit button text',
            ratingButtonColor: 'rating button color',
            ratingButtonActiveColor: 'active rating button color',
            borderColor: 'border color',
            placeholder: 'placeholder text',
            whiteLabel: 'white label option',
            displayThankYouMessage: 'thank you message display',
            thankYouMessageHeader: 'thank you message header',
            thankYouMessageDescription: 'thank you message description',
            thankYouMessageDescriptionContentType: 'thank you message content type',
            thankYouMessageCloseButtonText: 'thank you message close button text',
            autoDisappear: 'auto-disappear option',
            position: 'survey position',
            shuffleQuestions: 'question shuffling',
            surveyPopupDelaySeconds: 'survey popup delay',
            widgetType: 'widget type',
            widgetSelector: 'widget selector',
            widgetLabel: 'widget label',
            widgetColor: 'widget color',
        }

        const appearanceFields = Object.keys(fieldNameMapping) as (keyof SurveyAppearance)[]

        appearanceFields.forEach((field) => {
            const before = beforeAppearance?.[field]
            const after = afterAppearance?.[field]
            const readableFieldName = fieldNameMapping[field]

            if (!isEmptyOrUndefined(before) || !isEmptyOrUndefined(after)) {
                if (isEmptyOrUndefined(before) && !isEmptyOrUndefined(after)) {
                    changes.push(
                        <>
                            set {readableFieldName} to <strong>{String(after)}</strong>
                        </>
                    )
                } else if (!isEmptyOrUndefined(before) && isEmptyOrUndefined(after)) {
                    changes.push(
                        <>
                            removed {readableFieldName} (was <strong>{String(before)}</strong>)
                        </>
                    )
                } else if (before !== after) {
                    changes.push(
                        <>
                            changed {readableFieldName} from{' '}
                            {!isEmptyOrUndefined(before) ? <strong>{String(before)}</strong> : <i>unset</i>} to{' '}
                            <strong>{String(after)}</strong>
                        </>
                    )
                }
            }
        })

        return changes.length > 0
            ? {
                  description: changes,
              }
            : null
    },
    conditions: function onConditions(change) {
        const beforeConditions = change?.before as Survey['conditions']
        const afterConditions = change?.after as Survey['conditions']
        const changes: JSX.Element[] = []

        if (!isEmptyOrUndefined(beforeConditions?.url) || !isEmptyOrUndefined(afterConditions?.url)) {
            if (isEmptyOrUndefined(beforeConditions?.url) && !isEmptyOrUndefined(afterConditions?.url)) {
                changes.push(
                    <>
                        set URL condition to <strong>{afterConditions?.url}</strong>
                    </>
                )
            } else if (!isEmptyOrUndefined(beforeConditions?.url) && isEmptyOrUndefined(afterConditions?.url)) {
                changes.push(
                    <>
                        removed URL condition (was <strong>{beforeConditions?.url}</strong>)
                    </>
                )
            } else if (beforeConditions?.url !== afterConditions?.url) {
                changes.push(
                    <>
                        changed URL condition from{' '}
                        {!isEmptyOrUndefined(beforeConditions?.url) ? (
                            <strong>{beforeConditions?.url}</strong>
                        ) : (
                            <i>unset</i>
                        )}{' '}
                        to <strong>{afterConditions?.url}</strong>
                    </>
                )
            }
        }

        if (!isEmptyOrUndefined(beforeConditions?.selector) || !isEmptyOrUndefined(afterConditions?.selector)) {
            if (isEmptyOrUndefined(beforeConditions?.selector) && !isEmptyOrUndefined(afterConditions?.selector)) {
                changes.push(
                    <>
                        set selector to <strong>{afterConditions?.selector}</strong>
                    </>
                )
            } else if (
                !isEmptyOrUndefined(beforeConditions?.selector) &&
                isEmptyOrUndefined(afterConditions?.selector)
            ) {
                changes.push(
                    <>
                        removed selector (was <strong>{beforeConditions?.selector}</strong>)
                    </>
                )
            } else if (beforeConditions?.selector !== afterConditions?.selector) {
                changes.push(
                    <>
                        changed selector from{' '}
                        {!isEmptyOrUndefined(beforeConditions?.selector) ? (
                            <strong>{beforeConditions?.selector}</strong>
                        ) : (
                            <i>unset</i>
                        )}{' '}
                        to <strong>{afterConditions?.selector}</strong>
                    </>
                )
            }
        }

        if (
            !isEmptyOrUndefined(beforeConditions?.seenSurveyWaitPeriodInDays) ||
            !isEmptyOrUndefined(afterConditions?.seenSurveyWaitPeriodInDays)
        ) {
            if (
                isEmptyOrUndefined(beforeConditions?.seenSurveyWaitPeriodInDays) &&
                !isEmptyOrUndefined(afterConditions?.seenSurveyWaitPeriodInDays)
            ) {
                changes.push(
                    <>
                        set wait period to <strong>{afterConditions?.seenSurveyWaitPeriodInDays} days</strong>
                    </>
                )
            } else if (
                !isEmptyOrUndefined(beforeConditions?.seenSurveyWaitPeriodInDays) &&
                isEmptyOrUndefined(afterConditions?.seenSurveyWaitPeriodInDays)
            ) {
                changes.push(
                    <>
                        removed wait period (was <strong>{beforeConditions?.seenSurveyWaitPeriodInDays} days</strong>)
                    </>
                )
            } else if (beforeConditions?.seenSurveyWaitPeriodInDays !== afterConditions?.seenSurveyWaitPeriodInDays) {
                changes.push(
                    <>
                        changed wait period from{' '}
                        {!isEmptyOrUndefined(beforeConditions?.seenSurveyWaitPeriodInDays) ? (
                            <strong>{beforeConditions?.seenSurveyWaitPeriodInDays} days</strong>
                        ) : (
                            <i>unset</i>
                        )}{' '}
                        to <strong>{afterConditions?.seenSurveyWaitPeriodInDays} days</strong>
                    </>
                )
            }
        }

        if (!isEmptyOrUndefined(beforeConditions?.urlMatchType) || !isEmptyOrUndefined(afterConditions?.urlMatchType)) {
            if (beforeConditions?.urlMatchType !== afterConditions?.urlMatchType) {
                changes.push(
                    <>
                        changed URL match type from{' '}
                        {!isEmptyOrUndefined(beforeConditions?.urlMatchType) ? (
                            <strong>{beforeConditions?.urlMatchType}</strong>
                        ) : (
                            <i>unset</i>
                        )}{' '}
                        to <strong>{afterConditions?.urlMatchType}</strong>
                    </>
                )
            }
        }

        // Use JSON.stringify for deep comparison of objects
        if (JSON.stringify(beforeConditions?.events) !== JSON.stringify(afterConditions?.events)) {
            changes.push(<>modified event conditions</>)
        }

        return changes.length > 0
            ? {
                  description: changes,
              }
            : null
    },
    responses_limit: function onResponsesLimit(change) {
        if (isEmptyOrUndefined(change?.after)) {
            return {
                description: [<>removed response limit</>],
            }
        }
        return {
            description: [
                <>
                    set response limit to <strong>{change?.after as number}</strong>
                </>,
            ],
        }
    },
    iteration_count: function onIterationCount(change) {
        return {
            description: [
                <>
                    changed the iteration count to <strong>{change?.after as number}</strong>
                </>,
            ],
        }
    },
    iteration_frequency_days: function onIterationFrequency(change) {
        return {
            description: [
                <>
                    changed the iteration frequency to <strong>{change?.after as number} days</strong>
                </>,
            ],
        }
    },
}

export function surveyActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope !== 'Survey') {
        console.error('survey describer received a non-survey activity')
        return { description: null }
    }

    const user = <strong>{userNameForLogItem(logItem)}</strong>
    const surveyLink = nameOrLinkToSurvey(logItem?.item_id, logItem?.detail.name, logItem.activity)

    if (logItem.activity === 'created') {
        return {
            description: (
                <>
                    {user} created {surveyLink}
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            description: (
                <>
                    {user} deleted {surveyLink}
                </>
            ),
        }
    }

    if (logItem.activity === 'updated') {
        const changes: { field: string; description: Description }[] = []

        for (const change of logItem.detail.changes || []) {
            if (!change?.field) {
                continue
            }

            const possibleLogItem = surveyActionsMapping[change.field]?.(change, logItem)
            if (possibleLogItem?.description) {
                if (Array.isArray(possibleLogItem.description) && possibleLogItem.description.length > 1) {
                    // This is for conditions, which may have multiple changes
                    changes.push(
                        ...possibleLogItem.description.map((desc) => ({
                            field: 'conditions',
                            description: desc,
                        }))
                    )
                } else {
                    changes.push({
                        field: change.field,
                        description: possibleLogItem.description[0],
                    })
                }
            }
        }

        if (changes.length === 1) {
            const { field, description } = changes[0]
            const preposition = field === 'conditions' ? 'for' : getPreposition(field)
            return {
                description: (
                    <>
                        {user} {description} {preposition} {surveyLink}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                description: (
                    <>
                        {user} made multiple changes to {surveyLink}:
                        <ul className="bullet-list">
                            {changes.map(({ description }, index) => (
                                <li key={index}>{description}</li>
                            ))}
                        </ul>
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, surveyLink)
}
function getPreposition(field: string): string {
    switch (field) {
        case 'name':
        case 'description':
        case 'questions':
        case 'appearance':
        case 'type':
            return 'of'
        case 'responses_limit':
        case 'iteration_count':
        case 'iteration_frequency_days':
            return 'for'
        case 'archived':
        case 'start_date':
        case 'end_date':
            return ''
        default:
            return 'of'
    }
}
