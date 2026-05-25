import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import React, { useLayoutEffect, useMemo, useState } from 'react'

import { IconCollapse, IconDashboard, IconExpand, IconEye, IconHide, IconRewindPlay, IconWarning } from '@posthog/icons'
import { LemonButton, lemonToast } from '@posthog/lemon-ui'

import { AddToDashboardModal } from 'lib/components/AddToDashboard/AddToDashboardModal'
import {
    InsightBreakdownSummary,
    PropertiesSummary,
    SeriesSummary,
} from 'lib/components/Cards/InsightCard/InsightDetails'
import { TopHeading } from 'lib/components/Cards/InsightCard/TopHeading'
import { FEATURE_FLAGS } from 'lib/constants'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightsApi } from 'scenes/insights/utils/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import {
    ArtifactMessage,
    ArtifactSource,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isFunnelsQuery, isHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ReplayTabs } from '~/types'

import { MessageStatus } from '../maxLogic'
import { visualizationTypeToQuery } from '../utils'
import { MessageTemplate } from './MessageTemplate'
import { buildRecordingFiltersFromQuery, deriveInsightName } from './visualizationArtifactAnswer.helpers'

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

const QUERY_CONTEXT_POSTHOG_AI: QueryContext = { limitContext: 'posthog_ai' } as const

type FollowupAction = 'open_new_tab' | 'save_as_insight' | 'add_to_dashboard' | 'see_recordings'

interface FollowupCaptureContext {
    followup_actions_enabled: boolean
    is_saved_insight: boolean
    post_save?: boolean
}

function captureFollowupAction(
    action: FollowupAction,
    context: FollowupCaptureContext,
    extra: Record<string, unknown> = {}
): void {
    posthog.capture('max artifact action clicked', { action, ...context, ...extra })
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
    const { featureFlags } = useValues(featureFlagLogic)
    const followupActionsEnabled = featureFlags[FEATURE_FLAGS.MAX_FOLLOWUP_ACTIONS] === 'test'

    const [isSummaryShown, setIsSummaryShown] = useState(false)
    const [isCollapsed, setIsCollapsed] = useState(isEditingInsight)
    const [savedShortId, setSavedShortId] = useState<InsightShortId | null>(null)
    const [isSaving, setIsSaving] = useState(false)
    const [addToDashboardModalOpen, setAddToDashboardModalOpen] = useState(false)

    useLayoutEffect(() => {
        setIsCollapsed(isEditingInsight)
    }, [isEditingInsight])

    // Build query from either artifact content or inline visualization message
    const query = useMemo(() => {
        return visualizationTypeToQuery(content)
    }, [content])

    // Get the raw query for height calculation
    const rawQuery = content.query

    const effectiveShortId = savedShortId ?? (isSavedInsight ? (message.artifact_id as InsightShortId) : null)
    const insightQuery = query as InsightVizNode | DataVisualizationNode | null
    const recordingFilters = useMemo(
        () => (insightQuery ? buildRecordingFiltersFromQuery(insightQuery) : null),
        [insightQuery]
    )

    const captureContext: FollowupCaptureContext = {
        followup_actions_enabled: followupActionsEnabled,
        is_saved_insight: Boolean(effectiveShortId),
    }

    const handleSaveAsInsight = async (followWith: FollowupAction = 'save_as_insight'): Promise<void> => {
        if (!insightQuery || isSaving || effectiveShortId) {
            return
        }
        captureFollowupAction(followWith, captureContext)
        setIsSaving(true)
        try {
            const insight = await insightsApi.create({
                name: deriveInsightName(insightQuery),
                query: insightQuery,
                saved: true,
            })
            setSavedShortId(insight.short_id)
            if (followWith === 'save_as_insight') {
                lemonToast.success('Insight saved', {
                    button: {
                        label: 'View insight',
                        action: () => router.actions.push(urls.insightView(insight.short_id)),
                    },
                })
            } else if (followWith === 'add_to_dashboard') {
                setAddToDashboardModalOpen(true)
            }
        } catch (error) {
            const detail =
                error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string'
                    ? error.detail
                    : null
            lemonToast.error(detail ?? 'Could not save insight')
        } finally {
            setIsSaving(false)
        }
    }

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
                    <Query query={query} readOnly embedded context={QUERY_CONTEXT_POSTHOG_AI} />
                </div>
            )}
            <div className={clsx('flex items-center justify-between', !isCollapsed && 'mt-2')}>
                {isInsightVizNode(query) ? (
                    <div className="flex items-center gap-1.5">
                        <LemonButton
                            sideIcon={isSummaryShown ? <IconCollapse /> : <IconExpand />}
                            onClick={() => setIsSummaryShown(!isSummaryShown)}
                            size="xsmall"
                            className="-m-1 shrink"
                            tooltip={isSummaryShown ? 'Hide definition' : 'Show definition'}
                        >
                            <h5 className="m-0 leading-none">
                                <TopHeading query={query} />
                            </h5>
                        </LemonButton>
                    </div>
                ) : (
                    <h5 className="m-0 leading-none">
                        <TopHeading query={query} />
                    </h5>
                )}
                <div className="flex items-center gap-1.5">
                    {isEditingInsight && activeTabId && activeSceneId === Scene.Insight && (
                        <InsightSuggestionButton tabId={activeTabId} />
                    )}
                    {!isEditingInsight && followupActionsEnabled && !effectiveShortId && (
                        <>
                            <LemonButton
                                onClick={() => void handleSaveAsInsight('save_as_insight')}
                                loading={isSaving}
                                type="primary"
                                size="xsmall"
                                data-attr="max-artifact-save-as-insight"
                            >
                                Save as insight
                            </LemonButton>
                            <LemonButton
                                onClick={() => void handleSaveAsInsight('add_to_dashboard')}
                                loading={isSaving}
                                icon={<IconDashboard />}
                                size="xsmall"
                                data-attr="max-artifact-add-to-dashboard"
                                tooltip="Save and add to a dashboard"
                            />
                            {recordingFilters && (
                                <LemonButton
                                    to={urls.replay(ReplayTabs.Home, recordingFilters)}
                                    targetBlank
                                    icon={<IconRewindPlay />}
                                    size="xsmall"
                                    data-attr="max-artifact-see-recordings"
                                    tooltip="See recordings of these events"
                                    onClick={() => captureFollowupAction('see_recordings', captureContext)}
                                />
                            )}
                        </>
                    )}
                    {!isEditingInsight && followupActionsEnabled && effectiveShortId && (
                        <LemonButton
                            to={urls.insightView(effectiveShortId)}
                            targetBlank
                            type="primary"
                            size="xsmall"
                            icon={<IconOpenInNew />}
                            data-attr="max-artifact-open-saved-insight"
                            onClick={() =>
                                captureFollowupAction('open_new_tab', { ...captureContext, post_save: true })
                            }
                        >
                            Open insight
                        </LemonButton>
                    )}
                    {!isEditingInsight && !followupActionsEnabled && (
                        <LemonButton
                            to={
                                isSavedInsight
                                    ? urls.insightView(message.artifact_id as InsightShortId)
                                    : urls.insightNew({
                                          query: query as InsightVizNode | DataVisualizationNode,
                                      })
                            }
                            targetBlank
                            icon={<IconOpenInNew />}
                            size="xsmall"
                            tooltip={isSavedInsight ? 'Open insight' : 'Open as new insight'}
                            data-attr="max-artifact-open-as-new-insight"
                            onClick={() => captureFollowupAction('open_new_tab', captureContext)}
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
                        <div className="flex flex-wrap gap-4 mt-1 *:grow">
                            <PropertiesSummary properties={query.source.properties} />
                            <InsightBreakdownSummary query={query.source} />
                        </div>
                    )}
                </>
            )}
            {followupActionsEnabled && effectiveShortId && (
                <AddToDashboardModal
                    isOpen={addToDashboardModalOpen}
                    closeModal={() => setAddToDashboardModalOpen(false)}
                    insightProps={{ dashboardItemId: effectiveShortId }}
                    canEditInsight={true}
                />
            )}
        </MessageTemplate>
    )
})
