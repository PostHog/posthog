import { useActions, useValues } from 'kea'
import React, { useLayoutEffect, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { ArtifactMessage, VisualizationArtifactContent } from '~/queries/schema/schema-assistant-messages'

import { MessageStatus } from '../maxLogic'
import { VisualizationWidget, getArtifactOpenTarget } from './VisualizationWidget'

interface VisualizationArtifactProps {
    message: ArtifactMessage & { status?: MessageStatus }
    content: VisualizationArtifactContent
    status?: MessageStatus
    isEditingInsight: boolean
    activeSceneId?: string | null
}

function InsightSuggestionButton(): JSX.Element {
    const { insight } = useValues(insightSceneLogic)
    const insightProps = { dashboardItemId: insight?.short_id }
    const { suggestedQuery, previousQuery } = useValues(insightLogic(insightProps))
    const { onRejectSuggestedInsight, onReapplySuggestedInsight } = useActions(insightLogic(insightProps))

    return (
        <>
            {suggestedQuery && (
                <LemonButton
                    onClick={() => {
                        if (previousQuery) {
                            onRejectSuggestedInsight()
                        } else {
                            onReapplySuggestedInsight()
                        }
                    }}
                    sideIcon={previousQuery ? <IconCollapse /> : <IconExpand />}
                    size="xsmall"
                    tooltip={previousQuery ? 'Reject changes' : 'Reapply changes'}
                />
            )}
        </>
    )
}

/**
 * LangGraph-runtime proxy for visualization artifacts. Owns the scene coupling — collapse while
 * the insight editor consumes the result, the suggestion accept/reject button, and CTA hiding —
 * and delegates rendering to the atomic `VisualizationWidget`.
 */
export const VisualizationArtifact = React.memo(function VisualizationArtifact({
    message,
    content,
    status,
    isEditingInsight,
    activeSceneId,
}: VisualizationArtifactProps): JSX.Element | null {
    // Controlled collapse synced to edit mode — a key-remount would refetch the query instead.
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)

    useLayoutEffect(() => {
        setIsCollapsed(isEditingInsight)
    }, [isEditingInsight])

    if (status !== 'completed') {
        return null
    }

    const target = getArtifactOpenTarget(message, content)
    const showSuggestionButton = isEditingInsight && activeSceneId === Scene.Insight

    return (
        <VisualizationWidget
            content={content}
            openUrl={isEditingInsight ? null : target.url}
            openTooltip={target.tooltip}
            isCollapsed={isCollapsed}
            onCollapsedChange={setIsCollapsed}
            extraActions={showSuggestionButton ? <InsightSuggestionButton /> : null}
        />
    )
})
