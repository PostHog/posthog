import { renderSurveysPreview } from 'posthog-js'
import { useEffect, useRef } from 'react'

import { Survey } from '~/types'

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

    useEffect(() => {
        if (surveyPreviewRef.current) {
            // remove any existing survey preview
            surveyPreviewRef.current.innerHTML = ''
            renderSurveysPreview(null, survey, surveyPreviewRef.current, activePreview, questionIndex)
        }
    }, [survey, activePreview, questionIndex])
    return <div ref={surveyPreviewRef}>SurveyAppearancePreview</div>
}
