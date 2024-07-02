import { useValues } from 'kea'
import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useRef } from 'react'

import { Survey } from '~/types'

import { NewSurvey } from './constants'
import { surveysLogic } from './surveysLogic'

export function SurveyAppearancePreview({
    survey,
    previewPageIndex,
}: {
    survey: Survey | NewSurvey
    previewPageIndex: number
}): JSX.Element {
    const surveyPreviewRef = useRef<HTMLDivElement>(null)
    const feedbackWidgetPreviewRef = useRef<HTMLDivElement>(null)

    const { surveysHTMLAvailable } = useValues(surveysLogic)

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview({
                survey,
                parentElement: surveyPreviewRef.current,
                previewPageIndex,
                forceDisableHtml: !surveysHTMLAvailable,
            })
        }

        if (feedbackWidgetPreviewRef.current) {
            renderFeedbackWidgetPreview({
                survey,
                root: feedbackWidgetPreviewRef.current,
                forceDisableHtml: !surveysHTMLAvailable,
            })
        }
    }, [survey, previewPageIndex, surveysHTMLAvailable])
    return (
        <>
            <div ref={surveyPreviewRef} />
            <div ref={feedbackWidgetPreviewRef} />
        </>
    )
}
