import { useValues } from 'kea'
import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useRef } from 'react'
import { sanitizeSurveyAppearance } from 'scenes/surveys/utils'

import { Survey } from '~/types'

import { NewSurvey } from './constants'
import { surveysLogic } from './surveysLogic'

interface Props {
    survey: Survey | NewSurvey
    previewPageIndex: number
    onPreviewSubmit?: (res: string | string[] | number | null) => void
    positionStyles?: React.CSSProperties
}

const DEFAULT_POSITION_STYLES: React.CSSProperties = {
    position: 'relative',
    left: 'unset',
    right: 'unset',
    top: 'unset',
    bottom: 'unset',
    transform: 'unset',
    maxWidth: '100%',
}

export function SurveyAppearancePreview({
    survey,
    previewPageIndex,
    onPreviewSubmit = () => {},
    positionStyles = DEFAULT_POSITION_STYLES,
}: Props): JSX.Element {
    const surveyPreviewRef = useRef<HTMLDivElement>(null)
    const feedbackWidgetPreviewRef = useRef<HTMLDivElement>(null)

    const { surveysHTMLAvailable } = useValues(surveysLogic)

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview({
                survey: {
                    ...survey,
                    appearance: { ...sanitizeSurveyAppearance(survey.appearance), zIndex: 100 },
                },
                parentElement: surveyPreviewRef.current,
                previewPageIndex,
                forceDisableHtml: !surveysHTMLAvailable,
                onPreviewSubmit,
                positionStyles,
            })
        }

        if (feedbackWidgetPreviewRef.current) {
            renderFeedbackWidgetPreview({
                survey: {
                    ...survey,
                    appearance: sanitizeSurveyAppearance(survey.appearance),
                },
                root: feedbackWidgetPreviewRef.current,
                forceDisableHtml: !surveysHTMLAvailable,
            })
        }
    }, [survey, previewPageIndex, surveysHTMLAvailable, onPreviewSubmit, positionStyles])

    return <div ref={surveyPreviewRef} />
}
