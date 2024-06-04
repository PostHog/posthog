import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys-module-previews'
import { useEffect, useRef } from 'react'

import { Survey } from '~/types'

import { NewSurvey } from './constants'

export function SurveyAppearancePreview({
    survey,
    previewPageIndex,
}: {
    survey: Survey | NewSurvey
    previewPageIndex: number
}): JSX.Element {
    const surveyPreviewRef = useRef<HTMLDivElement>(null)
    const feedbackWidgetPreviewRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview(survey, surveyPreviewRef.current, previewPageIndex)
        }

        if (feedbackWidgetPreviewRef.current) {
            renderFeedbackWidgetPreview(survey, feedbackWidgetPreviewRef.current)
        }
    }, [survey, previewPageIndex])
    return (
        <>
            <div ref={surveyPreviewRef} />
            <div ref={feedbackWidgetPreviewRef} />
        </>
    )
}
