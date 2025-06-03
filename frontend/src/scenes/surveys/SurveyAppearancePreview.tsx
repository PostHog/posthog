import { useValues } from 'kea'
import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useRef } from 'react'
import { sanitizeSurvey } from 'scenes/surveys/utils'

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

    const sanitizedSurvey = sanitizeSurvey(survey)

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview({
                survey: {
                    ...sanitizedSurvey,
                    appearance: {
                        ...sanitizedSurvey.appearance,
                        zIndex: 1,
                    },
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
                    ...sanitizedSurvey,
                    appearance: {
                        ...sanitizedSurvey.appearance,
                        zIndex: 1,
                    },
                },
                root: feedbackWidgetPreviewRef.current,
                forceDisableHtml: !surveysHTMLAvailable,
            })
        }
    }, [survey, previewPageIndex, surveysHTMLAvailable, onPreviewSubmit, positionStyles])

    return <div ref={surveyPreviewRef} />
}
