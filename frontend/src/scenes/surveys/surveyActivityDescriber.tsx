import { P, match } from 'ts-pattern'

import {
    ActivityChange,
    ActivityLogItem,
    ChangeMapping,
    Description,
    HumanizedChange,
    defaultDescriber,
    detectBoolean,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { Link } from 'lib/lemon-ui/Link'
import { truncate } from 'lib/utils'
import { urls } from 'scenes/urls'

import {
    BasicSurveyQuestion,
    FeatureFlagBasicType,
    FeatureFlagFilters,
    LinkSurveyQuestion,
    MultipleSurveyQuestion,
    RatingSurveyQuestion,
    Survey,
    SurveyAppearance,
    SurveyQuestionType,
} from '~/types'

import { SurveyQuestionLabel } from './constants'

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
    name: function onName(change) {
        return {
            description: [
                <>
                    changed the name from <strong>"{change?.before as string}"</strong> to{' '}
                    <strong>"{change?.after as string}"</strong>
                </>,
            ],
        }
    },
    description: function onDescription(change) {
        return {
            description: [
                <>
                    updated the description from {formatDescription(change?.before as string | null | undefined)} to{' '}
                    {formatDescription(change?.after as string | null | undefined)}
                </>,
            ],
        }
    },
    type: function onType(change) {
        return {
            description: [
                <>
                    changed the type from <strong>{change?.before as string}</strong> to{' '}
                    <strong>{change?.after as string}</strong>
                </>,
            ],
        }
    },
    questions: function onQuestions(change?: ActivityChange): ChangeMapping | null {
        if (!change) {
            return null
        }

        const beforeQuestions = change.before as Survey['questions']
        const afterQuestions = change.after as Survey['questions']

        if (beforeQuestions.length !== afterQuestions.length) {
            return {
                description: [
                    <>
                        changed the number of questions from <strong>{beforeQuestions.length}</strong> to{' '}
                        <strong>{afterQuestions.length}</strong>
                    </>,
                ],
            }
        }

        const questionChanges = afterQuestions
            .map((afterQ, index) => {
                const beforeQ = beforeQuestions[index]
                if (JSON.stringify(beforeQ) !== JSON.stringify(afterQ)) {
                    return {
                        index: index + 1,
                        changes: describeQuestionChanges(beforeQ, afterQ),
                    }
                }
                return null
            })
            .filter((item): item is { index: number; changes: JSX.Element[] } => item !== null)

        if (questionChanges.length === 0) {
            return {
                description: [<>No changes to questions</>],
            }
        }

        return {
            description: [
                <>
                    updated <strong>{questionChanges.length}</strong> question{questionChanges.length !== 1 ? 's' : ''}:
                    <ul className="bullet-list">
                        {questionChanges.map(({ index, changes }) => (
                            <li key={index}>
                                Question {index}:
                                <ul className="bullet-list">
                                    {changes.map((changeItem, changeIndex) => (
                                        <li key={changeIndex}>{changeItem}</li>
                                    ))}
                                </ul>
                            </li>
                        ))}
                    </ul>
                </>,
            ],
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
        if (change?.before !== null && change?.after === null) {
            return {
                description: [<>resumed</>],
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
            submitButtonTextColor: 'submit button text color',
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
            zIndex: 'survey form zIndex',
            fontFamily: 'font family',
            disabledButtonOpacity: 'disabled button opacity',
            boxPadding: 'box padding',
            boxShadow: 'box shadow',
            borderRadius: 'border radius',
            maxWidth: 'max width',
            textSubtleColor: 'text subtle color',
            inputBackground: 'input background',
        }

        Object.entries(fieldNameMapping).forEach(([field, readableFieldName]) => {
            const before = beforeAppearance?.[field as keyof SurveyAppearance]
            const after = afterAppearance?.[field as keyof SurveyAppearance]
            const changeDescription = describeFieldChange(readableFieldName, before, after)
            if (changeDescription.props.children) {
                changes.push(changeDescription)
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

        changes.push(
            describeFieldChange('URL condition', beforeConditions?.url, afterConditions?.url),
            describeFieldChange('selector', beforeConditions?.selector, afterConditions?.selector),
            describeFieldChange(
                'wait period',
                beforeConditions?.seenSurveyWaitPeriodInDays,
                afterConditions?.seenSurveyWaitPeriodInDays,
                'days'
            ),
            describeFieldChange('URL match type', beforeConditions?.urlMatchType, afterConditions?.urlMatchType)
        )

        // Use JSON.stringify for deep comparison of objects
        if (JSON.stringify(beforeConditions?.events) !== JSON.stringify(afterConditions?.events)) {
            changes.push(<>modified event conditions</>)
        }

        return changes.filter((change) => change.props.children).length > 0
            ? {
                  description: changes.filter((change) => change.props.children),
              }
            : null
    },
    responses_limit: function onResponsesLimit(change) {
        return {
            description: [describeFieldChange('response limit', change?.before, change?.after, 'responses')].filter(
                (desc) => desc.props.children
            ),
        }
    },
    iteration_count: function onIterationCount(change) {
        return {
            description: [describeFieldChange('iteration count', change?.before, change?.after)].filter(
                (desc) => desc.props.children
            ),
        }
    },
    iteration_frequency_days: function onIterationFrequency(change) {
        return {
            description: [describeFieldChange('iteration frequency', change?.before, change?.after, 'days')].filter(
                (desc) => desc.props.children
            ),
        }
    },
    targeting_flag: function onTargetingFlag(change) {
        const beforeFlag = change?.before as FeatureFlagBasicType | null
        const afterFlag = change?.after as FeatureFlagBasicType | null
        const changes: Description[] = []

        if (!beforeFlag && afterFlag) {
            changes.push(
                <>
                    added a targeting flag with key <strong>{afterFlag.key}</strong>
                </>
            )
            if (afterFlag.filters?.groups?.length > 0) {
                changes.push(<>set new targeting conditions</>)
            }
        } else if (beforeFlag && !afterFlag) {
            changes.push(
                <>
                    removed the targeting flag with key <strong>{beforeFlag.key}</strong>
                </>
            )
        } else if (beforeFlag && afterFlag) {
            if (beforeFlag.key !== afterFlag.key) {
                changes.push(
                    <>
                        changed targeting flag key from <strong>{beforeFlag.key}</strong> to{' '}
                        <strong>{afterFlag.key}</strong>
                    </>
                )
            }
        }

        return changes.length > 0
            ? {
                  description: changes,
              }
            : null
    },
    targeting_flag_filters: function onTargetingFlagFilter(change) {
        const beforeFlag = change?.before as FeatureFlagFilters | null
        const afterFlag = change?.after as FeatureFlagFilters | null
        const changes: Description[] = []

        if (!beforeFlag && afterFlag) {
            changes.push(<>added a targeting flag filter</>)
        } else if (beforeFlag && !afterFlag) {
            changes.push(<>removed targeting flag filter</>)
        } else if (beforeFlag && afterFlag) {
            if (JSON.stringify(beforeFlag) !== JSON.stringify(afterFlag)) {
                changes.push(<>changed targeting conditions</>)
            }
        }

        return changes.length > 0
            ? {
                  description: changes,
              }
            : null
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
                    // This is for the conditions section, which may have multiple changes.
                    // Probably could be refactored into a separate handler like some of the other fields
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

export function getPreposition(field: string): string {
    switch (field) {
        case 'questions':
        case 'appearance':
        case 'type':
            return 'of'
        case 'name':
        case 'description':
        case 'responses_limit':
        case 'iteration_count':
        case 'iteration_frequency_days':
        case 'targeting_flag_filters':
        case 'targeting_flag':
            return 'for'
        case 'archived':
        case 'start_date':
        case 'end_date':
            return ''
        default:
            return 'of'
    }
}

type SurveyQuestion = BasicSurveyQuestion | LinkSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion

export function describeQuestionChanges(before: SurveyQuestion, after: SurveyQuestion): JSX.Element[] {
    const commonChanges = describeCommonChanges(before, after)
    const typeChangeDescription =
        before.type !== after.type
            ? [
                  <>
                      changed question type from <strong>{SurveyQuestionLabel[before.type]}</strong> to{' '}
                      <strong>{SurveyQuestionLabel[after.type]}</strong>
                  </>,
              ]
            : []

    const specificChanges = match([before, after])
        .with([{ type: SurveyQuestionType.Link }, { type: SurveyQuestionType.Link }], describeLinkChanges)
        .with([{ type: SurveyQuestionType.Rating }, { type: SurveyQuestionType.Rating }], describeRatingChanges)
        .with(
            [
                { type: P.union(SurveyQuestionType.SingleChoice, SurveyQuestionType.MultipleChoice) },
                { type: P.union(SurveyQuestionType.SingleChoice, SurveyQuestionType.MultipleChoice) },
            ],
            describeMultipleChoiceChanges
        )
        .otherwise(() => [])

    return [...commonChanges, ...typeChangeDescription, ...specificChanges, ...describeBranchingChanges(before, after)]
}

export function describeCommonChanges(before: SurveyQuestion, after: SurveyQuestion): JSX.Element[] {
    const changes: JSX.Element[] = []
    if (before.question !== after.question) {
        changes.push(
            <>
                changed question text from "<strong>{before.question}</strong>" to "<strong>{after.question}</strong>"
            </>
        )
    }
    if (before.description !== after.description) {
        changes.push(
            <>
                changed the question description from {formatDescription(before.description)} to{' '}
                {formatDescription(after.description)}
            </>
        )
    }
    if (before.optional !== after.optional) {
        changes.push(<>{after.optional ? 'made question optional' : 'made question required'}</>)
    }
    if (before.buttonText !== after.buttonText) {
        changes.push(
            <>
                changed button text from "<strong>{before.buttonText}</strong>" to "<strong>{after.buttonText}</strong>"
            </>
        )
    }
    return changes
}

export function describeLinkChanges([before, after]: [LinkSurveyQuestion, LinkSurveyQuestion]): JSX.Element[] {
    return before.link !== after.link
        ? [
              <>
                  updated link from <strong>{before.link}</strong> to <strong>{after.link}</strong>
              </>,
          ]
        : []
}

export function describeRatingChanges([before, after]: [RatingSurveyQuestion, RatingSurveyQuestion]): JSX.Element[] {
    const changes: JSX.Element[] = []
    if (before.display !== after.display) {
        changes.push(
            <>
                changed rating display from <strong>{before.display}</strong> to <strong>{after.display}</strong>
            </>
        )
    }
    if (before.scale !== after.scale) {
        changes.push(
            <>
                changed rating scale from <strong>{before.scale}</strong> to <strong>{after.scale}</strong>
            </>
        )
    }
    if (before.lowerBoundLabel !== after.lowerBoundLabel || before.upperBoundLabel !== after.upperBoundLabel) {
        changes.push(
            <>
                updated rating labels from <strong>"{before.lowerBoundLabel}"</strong>-
                <strong>"{before.upperBoundLabel}"</strong> to <strong>"{after.lowerBoundLabel}"</strong>-
                <strong>"{after.upperBoundLabel}"</strong>
            </>
        )
    }
    return changes
}

export function describeMultipleChoiceChanges([before, after]: [
    MultipleSurveyQuestion,
    MultipleSurveyQuestion,
]): JSX.Element[] {
    const changes: JSX.Element[] = []
    if (JSON.stringify(before.choices) !== JSON.stringify(after.choices)) {
        const addedChoices = after.choices.filter((c) => !before.choices.includes(c))
        const removedChoices = before.choices.filter((c) => !after.choices.includes(c))
        if (addedChoices.length > 0) {
            changes.push(
                <>
                    added choices: <strong>{addedChoices.join(', ')}</strong>
                </>
            )
        }
        if (removedChoices.length > 0) {
            changes.push(
                <>
                    removed choices: <strong>{removedChoices.join(', ')}</strong>
                </>
            )
        }
    }
    if (before.shuffleOptions !== after.shuffleOptions) {
        changes.push(<>{after.shuffleOptions ? 'enabled' : 'disabled'} option shuffling</>)
    }
    if (before.hasOpenChoice !== after.hasOpenChoice) {
        changes.push(<>{after.hasOpenChoice ? 'added' : 'removed'} open choice option</>)
    }
    return changes
}

export function describeBranchingChanges(before: SurveyQuestion, after: SurveyQuestion): JSX.Element[] {
    if (JSON.stringify(before.branching) !== JSON.stringify(after.branching)) {
        return [<>updated branching logic</>]
    }
    return []
}

export const formatDescription = (value: string | null | undefined): JSX.Element => {
    if (value === undefined || value === null || value === '') {
        return <i>unset</i>
    }
    return <strong>"{truncate(value, 50)}"</strong>
}

export function describeFieldChange<T>(fieldName: string, before: T, after: T, unit?: string): JSX.Element {
    if (isEmptyOrUndefined(before) && isEmptyOrUndefined(after)) {
        return <></>
    }
    if (isEmptyOrUndefined(before) && !isEmptyOrUndefined(after)) {
        return (
            <>
                set {fieldName} to{' '}
                <strong>
                    {String(after)}
                    {unit ? ` ${unit}` : ''}
                </strong>
            </>
        )
    } else if (!isEmptyOrUndefined(before) && isEmptyOrUndefined(after)) {
        return (
            <>
                removed {fieldName} (was{' '}
                <strong>
                    {String(before)}
                    {unit ? ` ${unit}` : ''}
                </strong>
                )
            </>
        )
    } else if (before !== after) {
        return (
            <>
                changed {fieldName} from{' '}
                <strong>
                    {String(before)}
                    {unit ? ` ${unit}` : ''}
                </strong>{' '}
                to{' '}
                <strong>
                    {String(after)}
                    {unit ? ` ${unit}` : ''}
                </strong>
            </>
        )
    }
    return <></>
}
