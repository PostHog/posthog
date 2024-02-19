import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys.esm'
import { useEffect, useRef } from 'react'

import { Survey, SurveyType } from '~/types'

export function SurveyAppearancePreview({
    survey,
    activePreview,
    questionIndex,
}: {
    survey: Survey
    activePreview: 'survey' | 'confirmation'
    questionIndex: number
}): JSX.Element {
    const surveyPreviewRef = useRef<HTMLDivElement>(null)
    const feedbackWidgetPreviewRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (surveyPreviewRef.current) {
            // remove any existing survey preview
            surveyPreviewRef.current.innerHTML = ''
            renderSurveysPreview(survey, surveyPreviewRef.current, activePreview, questionIndex)
        }

        if (feedbackWidgetPreviewRef.current) {
            if (survey.type === SurveyType.Widget && survey.appearance.widgetType === 'tab') {
                // remove any existing feedback widget preview
                feedbackWidgetPreviewRef.current.innerHTML = ''
                renderFeedbackWidgetPreview(survey, feedbackWidgetPreviewRef.current)
            } else {
                feedbackWidgetPreviewRef.current.innerHTML = ''
            }
        }
    }, [survey, activePreview, questionIndex])
    return (
        <>
            <div ref={surveyPreviewRef} />
            <div ref={feedbackWidgetPreviewRef} />
        </>
    )
}

export function FeedbackWidgetAppearancePreview({ survey }: { survey: Survey }): JSX.Element {
    const feedbackWidgetPreviewRef = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (feedbackWidgetPreviewRef.current) {
            // remove any existing feedback widget preview
            feedbackWidgetPreviewRef.current.innerHTML = ''
            renderFeedbackWidgetPreview(survey, feedbackWidgetPreviewRef.current)
        }
    }, [survey.type, survey.appearance])
    return <div ref={feedbackWidgetPreviewRef}>FeedbackWidgetAppearancePreview</div>
}
