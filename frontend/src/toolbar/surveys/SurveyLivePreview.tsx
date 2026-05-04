import { useValues } from 'kea'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useRef } from 'react'

import { SIDEBAR_WIDTH } from './constants'
import { surveysToolbarLogic } from './surveysToolbarLogic'

const PREVIEW_CONTAINER_ID = '__posthog_toolbar_survey_preview__'

const PREVIEW_POSITION_STYLES: React.CSSProperties = {
    position: 'fixed',
    zIndex: '2147482647',
    bottom: '0',
    right: `${SIDEBAR_WIDTH + 16}px`,
}

/**
 * Renders a live survey preview directly on the page (outside the shadow DOM)
 * as the user fills in the quick-create form. The survey appears in its natural
 * position (e.g. bottom-right) exactly as end users would see it.
 */
export function SurveyLivePreview(): JSX.Element | null {
    const { previewSurvey, isCreating } = useValues(surveysToolbarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)

    // Create/destroy the preview container on the real page (outside shadow DOM)
    useEffect(() => {
        if (!isCreating) {
            return
        }

        let container = document.getElementById(PREVIEW_CONTAINER_ID) as HTMLDivElement | null
        if (!container) {
            container = document.createElement('div')
            container.id = PREVIEW_CONTAINER_ID
            document.body.appendChild(container)
        }
        containerRef.current = container

        return () => {
            container?.remove()
            containerRef.current = null
        }
    }, [isCreating])

    // Re-render the preview whenever the form changes.
    // renderSurveysPreview uses Preact internally — calling it again on the same
    // container lets Preact diff and update without destroying the tree.
    useEffect(() => {
        const container = containerRef.current
        if (!container || !previewSurvey) {
            return
        }

        try {
            renderSurveysPreview({
                survey: previewSurvey,
                parentElement: container,
                previewPageIndex: 0,
                positionStyles: PREVIEW_POSITION_STYLES,
            })
        } catch (e) {
            console.warn('[Toolbar] Survey preview render failed:', e)
        }
    }, [previewSurvey, isCreating])

    return null
}
