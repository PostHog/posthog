import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { IconLink } from 'lib/lemon-ui/icons'
import { surveyLogic } from 'scenes/surveys/surveyLogic'
import { getSurveyResponseValue } from 'scenes/surveys/utils'
import { urls } from 'scenes/urls'

import { SurveyEventProperties as SurveyEventPropertyNames, SurveyQuestion } from '~/types'

interface SurveyResponseDisplayProps {
    eventProperties: Record<string, any>
    eventUuid?: string
}

export function SurveyResponseDisplay({ eventProperties, eventUuid }: SurveyResponseDisplayProps): JSX.Element {
    const surveyId = eventProperties[SurveyEventPropertyNames.SURVEY_ID]

    const { location } = useValues(router)
    const isOnSurveyPage = surveyId && location.pathname.includes(`/surveys/${surveyId}`)

    const { survey, archivedResponseUuids } = useValues(surveyLogic({ id: surveyId }))
    const isArchived = eventUuid ? (archivedResponseUuids?.has(eventUuid) ?? false) : false

    const surveyName = survey?.name || eventProperties['$survey_name']

    const responses: { questionIndex: number; question: SurveyQuestion; value: any }[] = []

    if (survey?.questions) {
        survey.questions.forEach((q, index) => {
            const question = q as SurveyQuestion
            const value = getSurveyResponseValue(eventProperties, index, question.id)
            if (value !== undefined) {
                responses.push({ questionIndex: index, question, value })
            }
        })
    }

    return (
        <div className="flex flex-col gap-2 pb-2">
            <div className="flex flex-row gap-2 flex-wrap items-center">
                {surveyName && <h3 className="mb-0 mr-2">{surveyName}</h3>}
                {surveyId && !isOnSurveyPage && (
                    <Link to={urls.survey(surveyId)} className="flex items-center gap-1">
                        <IconLink className="text-sm" />
                        <span className="text-sm">View survey</span>
                    </Link>
                )}
            </div>

            {isArchived && (
                <div>
                    <LemonTag type="muted" icon={<IconArchive />}>
                        Response archived
                    </LemonTag>
                </div>
            )}

            {responses.length > 0 && (
                <div className="flex flex-col gap-3">
                    {responses.map(({ questionIndex, question, value }) => (
                        <div key={questionIndex} className="flex flex-col gap-1">
                            <span className="text-xs text-secondary font-semibold">{question.question}</span>
                            <span className="text-sm whitespace-pre-wrap">
                                {Array.isArray(value) ? value.join(', ') : value}
                            </span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
