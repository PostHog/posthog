import { useValues } from 'kea'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useMemo, useRef } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { SIDEBAR_WIDTH } from './constants'
import { surveysToolbarLogic, SURVEY_PREVIEW_Z_INDEX } from './surveysToolbarLogic'

const PREVIEW_CONTAINER_PREFIX = '__posthog_toolbar_survey_preview__'
const RENDER_DEBOUNCE_MS = 150

const PREVIEW_BASE_STYLES: React.CSSProperties = {
    position: 'fixed',
    zIndex: SURVEY_PREVIEW_Z_INDEX,
    bottom: 0,
}

/**
 * Renders a live survey preview directly on the page (outside the shadow DOM)
 * as the user fills in the quick-create form. The survey appears in its natural
 * position (bottom-right) exactly as end users would see it.
 *
 * Failure modes addressed:
 * - Container ID is suffixed per-mount so two toolbar instances don't collide.
 * - Renders are debounced so a fast typist doesn't trigger Preact diffs on every
 *   keystroke and (potentially) leak listeners through the upstream renderer.
 * - On viewports too narrow to fit the preview alongside the sidebar, the
 *   preview falls back to a centered position so it isn't clipped off-screen.
 * - If `renderSurveysPreview` throws, surface a one-time toast — silently
 *   no-op'ing makes the user think they typed something invalid.
 */
export function SurveyLivePreview(): JSX.Element | null {
    const { previewSurvey, isCreating } = useValues(surveysToolbarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const renderTimerRef = useRef<number | null>(null)
    const renderErrorWarnedRef = useRef(false)
    // One ID per mount to avoid collisions if a stranded container leaks.
    const containerId = useMemo(() => `${PREVIEW_CONTAINER_PREFIX}${Math.random().toString(36).slice(2)}`, [])

    // Create/destroy the preview container on the real page (outside shadow DOM)
    useEffect(() => {
        if (!isCreating) {
            return
        }
        const container = document.createElement('div')
        container.id = containerId
        document.body.appendChild(container)
        containerRef.current = container

        return () => {
            container.remove()
            containerRef.current = null
            renderErrorWarnedRef.current = false
        }
    }, [isCreating, containerId])

    // Debounce re-renders to ~150ms so per-keystroke typing doesn't spin the
    // upstream renderer.
    useEffect(() => {
        const container = containerRef.current
        if (!container || !previewSurvey) {
            return
        }
        if (renderTimerRef.current !== null) {
            window.clearTimeout(renderTimerRef.current)
        }
        renderTimerRef.current = window.setTimeout(() => {
            renderTimerRef.current = null
            try {
                // Position: align with the sidebar when there's room, otherwise
                // center bottom so it isn't clipped on narrow viewports.
                const fitsBesideSidebar = window.innerWidth > SIDEBAR_WIDTH + 320
                const positionStyles: React.CSSProperties = fitsBesideSidebar
                    ? { ...PREVIEW_BASE_STYLES, right: SIDEBAR_WIDTH + 16 }
                    : { ...PREVIEW_BASE_STYLES, left: '50%', transform: 'translateX(-50%)' }
                renderSurveysPreview({
                    survey: previewSurvey,
                    parentElement: container,
                    previewPageIndex: 0,
                    positionStyles,
                })
            } catch (e) {
                // eslint-disable-next-line no-console
                console.warn('[Toolbar] Survey preview render failed:', e)
                if (!renderErrorWarnedRef.current) {
                    renderErrorWarnedRef.current = true
                    lemonToast.warning("Survey preview couldn't render. Your save will still work.")
                }
            }
        }, RENDER_DEBOUNCE_MS)

        return () => {
            if (renderTimerRef.current !== null) {
                window.clearTimeout(renderTimerRef.current)
                renderTimerRef.current = null
            }
        }
    }, [previewSurvey])

    return null
}
