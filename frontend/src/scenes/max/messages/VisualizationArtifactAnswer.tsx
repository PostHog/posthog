import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React, { useLayoutEffect, useMemo, useState } from 'react'

import { IconCollapse, IconExpand, IconEye, IconHide, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    ArtifactMessage,
    ArtifactSource,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId } from '~/types'

import { MessageStatus } from '../maxLogic'
import { visualizationTypeToQuery } from '../utils'
import { MessageTemplate } from './MessageTemplate'

interface VisualizationArtifactAnswerProps {
    message: ArtifactMessage & { status?: MessageStatus }
    content: VisualizationArtifactContent
    status?: MessageStatus
    isEditingInsight: boolean
    activeTabId?: string | null
    activeSceneId?: string | null
}

function InsightSuggestionButton({ tabId }: { tabId: string }): JSX.Element {
    const { insight } = useValues(insightSceneLogic({ tabId }))
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

export const VisualizationArtifactAnswer = React.memo(function VisualizationArtifactAnswer({
    message,
    content,
    status,
    isEditingInsight,
    activeTabId,
    activeSceneId,
}: VisualizationArtifactAnswerProps): JSX.Element | null {
    const isSavedInsight = message.source === ArtifactSource.Insight

    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)

    useLayoutEffect(() => {
        setIsCollapsed(isEditingInsight)
    }, [isEditingInsight])

    // Build query from either artifact content or inline visualization message
    const query = useMemo(() => {
        return visualizationTypeToQuery(content)
    }, [content])

    // Get the raw query for height calculation
    const rawQuery = content.query

    if (status !== 'completed') {
        return null
    }

    if (!query) {
        return (
            <MessageTemplate
                type="ai"
                className="w-full"
                wrapperClassName="w-full"
                boxClassName="flex flex-col w-full border-danger"
            >
                <div className="flex items-center gap-1.5">
                    <IconWarning className="text-xl text-danger" />
                    <span>Failed to load visualization</span>
                </div>
            </MessageTemplate>
        )
    }

    return (
        <MessageTemplate type="ai" className="w-full" wrapperClassName="w-full" boxClassName="flex flex-col w-full">
            {!isCollapsed && (
                <div className={clsx('flex flex-col overflow-auto', isFunnelsQuery(rawQuery) ? 'h-[580px]' : 'h-96')}>
                    <Query query={query} readOnly embedded />
                </div>
            )}
            {!isCollapsed && <div className="h-px bg-border-primary -mx-3" />}
            <div className={clsx('flex items-center justify-between', !isCollapsed && 'mt-2')}>
                <div className="flex items-center gap-1.5">
                    <LemonButton
                        sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                        onClick={() => setIsSummaryShown(!isSummaryShown)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                    >
                        <span className="m-0 leading-none">
                            <TopHeading query={query} />
                        </span>
                    </LemonButton>
                </div>
                <div className="flex items-center gap-1.5">
                    {isEditingInsight && activeTabId && activeSceneId === Scene.Insight && (
                        <InsightSuggestionButton tabId={activeTabId} />
                    )}
                    {!isEditingInsight && (
                        <LemonButton
                            to={
                                isSavedInsight
                                    ? urls.insightView(message.artifact_id as InsightShortId)
                                    : urls.insightNew({
                                          query: query as InsightVizNode | DataVisualizationNode,
                                      })
                            }
                            icon={<IconOpenInNew />}
                            size="xsmall"
                            tooltip={isSavedInsight ? 'Open insight' : 'Open as new insight'}
                        />
                    )}
                    <LemonButton
                        icon={isCollapsed ? <IconEye /> : <IconHide />}
                        onClick={() => setIsCollapsed(!isCollapsed)}
                        size="xsmall"
                        className="-m-1 shrink"
                        tooltip={isCollapsed ? 'Show visualization' : 'Hide visualization'}
                    />
                </div>
            </div>
            {isInsightVizNode(query) && isSummaryShown && (
                <>
                    <SeriesSummary query={query.source} heading={null} />
                    {!isHogQLQuery(query.source) && (
                        <>
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </>
                    )}
                </>
            )}
        </MessageTemplate>
    )
})
