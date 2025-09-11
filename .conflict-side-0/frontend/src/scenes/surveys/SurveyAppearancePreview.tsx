import { renderFeedbackWidgetPreview, renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useMemo, useRef } from 'react'

import { sanitizeSurvey } from 'scenes/surveys/utils'

import { Survey } from '~/types'

import { NewSurvey } from './constants'

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

    const sanitizedSurvey = useMemo(
        () =>
            sanitizeSurvey({
                ...survey,
                appearance: {
                    ...survey.appearance,
                    zIndex: '1',
                },
            }),
        [survey]
    )

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview({
                survey: sanitizedSurvey,
                parentElement: surveyPreviewRef.current,
                previewPageIndex,
                onPreviewSubmit,
                positionStyles,
            })
        }

        if (feedbackWidgetPreviewRef.current) {
            renderFeedbackWidgetPreview({
                survey: sanitizedSurvey,
                root: feedbackWidgetPreviewRef.current,
            })
        }
    }, [survey, previewPageIndex, onPreviewSubmit, positionStyles]) // oxlint-disable-line react-hooks/exhaustive-deps

    return <div ref={surveyPreviewRef} />
}
