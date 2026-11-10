import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useMemo, useRef } from 'react'

import { objectClean } from 'lib/utils/objects'
import { sanitizeSurvey } from 'scenes/surveys/utils'

import { Survey } from '~/types'

import { NewSurvey } from './constants'

interface Props {
    survey: Survey | NewSurvey
    previewPageIndex: number
    onPreviewSubmit?: (res: string | string[] | number | null) => void
    onPreviewBack?: () => void
    positionStyles?: React.CSSProperties
}

const DEFAULT_POSITION_STYLES: React.CSSProperties = {
    position: 'relative',
    left: 'unset',
    right: 'unset',
    top: 'unset',
    bottom: 'unset',
    transform: 'unset',
    width: 'var(--ph-survey-max-width)',
    maxWidth: '100%',
    minWidth: 'min(300px, 100%)',
    boxSizing: 'border-box',
}

export function SurveyAppearancePreview({
    survey,
    previewPageIndex,
    onPreviewSubmit = () => {},
    onPreviewBack = () => {},
    positionStyles = DEFAULT_POSITION_STYLES,
}: Props): JSX.Element {
    const surveyPreviewRef = useRef<HTMLDivElement>(null)

    const sanitizedSurvey = useMemo(() => {
        const sanitized = sanitizeSurvey({
            ...survey,
            appearance: {
                ...survey.appearance,
                zIndex: '1',
            },
        })
        // posthog-js spreads the appearance over its defaults, so an unset color must be absent, not undefined,
        // or the preview draws a transparent survey that a site never shows.
        return { ...sanitized, appearance: sanitized.appearance && objectClean({ ...sanitized.appearance }) }
    }, [survey])

    useEffect(() => {
        if (surveyPreviewRef.current) {
            renderSurveysPreview({
                survey: sanitizedSurvey,
                parentElement: surveyPreviewRef.current,
                previewPageIndex,
                onPreviewSubmit,
                onPreviewBack,
                positionStyles,
            })
        }
    }, [survey, previewPageIndex, onPreviewSubmit, onPreviewBack, positionStyles]) // oxlint-disable-line react-hooks/exhaustive-deps

    return <div ref={surveyPreviewRef} className="flex w-full min-w-0 justify-center" />
}
