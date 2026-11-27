import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { sceneLogic } from 'scenes/sceneLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { agentTranscriptRequestLogic } from '../logics/agentTranscriptRequestLogic'
import { AgentTranscriptRequestCard } from './AgentTranscriptRequestCard'

const CARD_WIDTH_PX = 320
const CARD_OFFSET_PX = 16

/**
 * The request card, pinned to the bottom left corner of the scene area. It follows the scene's own
 * rectangle rather than the window, so it never covers the navigation, the side panel or the toasts,
 * which sit at the bottom right of the window.
 */
export function AgentTranscriptRequest(): JSX.Element | null {
    const { shouldShowRequest, variant, stage } = useValues(agentTranscriptRequestLogic)
    const { reportRequestShown, openRequest, dismissRequest } = useActions(agentTranscriptRequestLogic)
    const { mainContentRect } = useValues(panelLayoutLogic)
    const { sceneConfig } = useValues(sceneLogic)

    // A plain scene, such as onboarding, has no scene area, so the last measured rectangle is stale there.
    const hasSceneArea = !!mainContentRect && sceneConfig?.layout !== 'plain'
    const visible = shouldShowRequest && !!variant && hasSceneArea

    useEffect(() => {
        if (visible) {
            reportRequestShown()
        }
    }, [visible, reportRequestShown])

    if (!visible || !variant || !mainContentRect) {
        return null
    }

    return (
        <div
            className="fixed z-[var(--z-content-overlay)]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                left: mainContentRect.left + CARD_OFFSET_PX,
                bottom: window.innerHeight - mainContentRect.bottom + CARD_OFFSET_PX,
                width: Math.min(CARD_WIDTH_PX, mainContentRect.width - 2 * CARD_OFFSET_PX),
            }}
        >
            <AgentTranscriptRequestCard
                variant={variant}
                stage={stage}
                onOpen={openRequest}
                onDismiss={dismissRequest}
            />
        </div>
    )
}
