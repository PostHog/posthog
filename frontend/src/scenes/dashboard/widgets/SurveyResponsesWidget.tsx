import { useEffect, useState } from 'react'

import { IconComment } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { urls } from 'scenes/urls'

import { Survey, SurveyQuestionType } from '~/types'

interface SurveyResponsesWidgetProps {
    tileId: number
    config: Record<string, any>
}

function SurveyResponsesWidget({ config }: SurveyResponsesWidgetProps): JSX.Element {
    const [survey, setSurvey] = useState<Survey | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    const surveyId = config.survey_id

    useEffect(() => {
        if (!surveyId) {
            setError('No survey configured')
            setLoading(false)
            return
        }

        setLoading(true)
        api.get(`api/projects/@current/surveys/${surveyId}`)
            .then((data) => {
                setSurvey(data as Survey)
                setLoading(false)
            })
            .catch(() => {
                setError('Failed to load survey')
                setLoading(false)
            })
    }, [surveyId])

    if (loading) {
        return (
            <div className="p-4 space-y-3">
                <LemonSkeleton className="h-6 w-1/2" />
                <LemonSkeleton className="h-4 w-3/4" />
                <LemonSkeleton className="h-32 w-full" />
            </div>
        )
    }

    if (error || !survey) {
        return (
            <div className="p-4 flex flex-col items-center justify-center h-full text-muted">
                <IconComment className="text-3xl mb-2" />
                <span>{error || 'Survey not found'}</span>
            </div>
        )
    }

    const questions = survey.questions || []

    return (
        <div className="p-4 space-y-3 h-full overflow-auto">
            <div className="flex items-center gap-2">
                <h4 className="font-semibold text-base mb-0 flex-1 truncate">{survey.name}</h4>
                <span className="text-xs text-muted capitalize px-2 py-0.5 bg-surface-secondary rounded">
                    {survey.type}
                </span>
            </div>

            {questions.length > 0 && (
                <div className="space-y-2">
                    <div className="text-xs font-medium text-muted uppercase">
                        Questions ({questions.length})
                    </div>
                    {questions.map((question, index) => (
                        <div
                            key={index}
                            className="p-2 rounded border bg-surface-secondary text-sm"
                        >
                            <div className="font-medium truncate">{question.question}</div>
                            <div className="text-xs text-muted mt-0.5">
                                {questionTypeLabel(question.type)}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <div className="pt-2">
                <LemonButton type="secondary" size="small" to={urls.survey(surveyId)} fullWidth center>
                    View full survey
                </LemonButton>
            </div>
        </div>
    )
}

function questionTypeLabel(type: SurveyQuestionType): string {
    const labels: Record<string, string> = {
        [SurveyQuestionType.Open]: 'Open text',
        [SurveyQuestionType.Link]: 'Link',
        [SurveyQuestionType.Rating]: 'Rating',
        [SurveyQuestionType.SingleChoice]: 'Single choice',
        [SurveyQuestionType.MultipleChoice]: 'Multiple choice',
    }
    return labels[type] || type
}

export default SurveyResponsesWidget
