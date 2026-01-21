import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import {
    MaxErrorTrackingIssuePreview,
    MaxErrorTrackingSearchResponse,
} from '~/queries/schema/schema-assistant-error-tracking'
import { AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import {
    ErrorTrackingQueryOrderBy,
    ErrorTrackingQueryOrderDirection,
    ErrorTrackingQueryStatus,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { ERROR_TRACKING_SCENE_LOGIC_KEY } from 'products/error_tracking/frontend/scenes/ErrorTrackingScene/errorTrackingSceneLogic'

import { DangerousOperationApprovalCard } from '../DangerousOperationApprovalCard'
import { isDangerousOperationResponse, normalizeDangerousOperationResponse } from '../approvalOperationUtils'
import { maxLogic } from '../maxLogic'
import { ErrorTrackingFiltersSummary } from './ErrorTrackingFiltersSummary'
import { ErrorTrackingIssueCard } from './ErrorTrackingIssueCard'
import { MessageTemplate } from './MessageTemplate'
import { RecordingsFiltersSummary } from './RecordingsFiltersSummary'
import { MaxErrorTrackingWidgetLogicProps, maxErrorTrackingWidgetLogic } from './maxErrorTrackingWidgetLogic'

export const RENDERABLE_UI_PAYLOAD_TOOLS: AssistantTool[] = [
    'search_session_recordings',
    'search_error_tracking_issues',
    'create_form',
    'upsert_dashboard',
]

export function UIPayloadAnswer({
    toolCallId,
    toolName,
    toolPayload,
}: {
    toolCallId: string
    toolName: string
    toolPayload: any
}): JSX.Element | null {
    const { conversationId } = useValues(maxLogic)

    if (toolName === 'search_session_recordings') {
        const filters = toolPayload as RecordingUniversalFilters
        return <RecordingsWidget toolCallId={toolCallId} filters={filters} />
    }
    if (toolName === 'search_error_tracking_issues') {
        const filters = toolPayload as MaxErrorTrackingSearchResponse
        return <ErrorTrackingFiltersWidget toolCallId={toolCallId} filters={filters} />
    }

    // Check if this is a dangerous operation requiring approval
    if (isDangerousOperationResponse(toolPayload)) {
        if (!conversationId) {
            return null
        }
        const normalizedOperation = normalizeDangerousOperationResponse(toolPayload)
        return <DangerousOperationApprovalCard operation={normalizedOperation} />
    }

    // It's not expected to hit the null branch below, because such a case SHOULD have already been filtered out
    // in maxThreadLogic.selectors.threadGrouped, but better safe than sorry - there can be deployments mismatches etc.
    return null
}

export function RecordingsWidget({
    toolCallId,
    filters,
}: {
    toolCallId: string
    filters: RecordingUniversalFilters
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `ai-recordings-widget-${toolCallId}`,
        filters,
        updateSearchParams: false,
        autoPlay: false,
    }

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                <RecordingsFiltersSummary filters={filters} />
                <RecordingsListContent />
            </MessageTemplate>
        </BindLogic>
    )
}

function RecordingsListContent(): JSX.Element {
    const { otherRecordings, sessionRecordingsResponseLoading, hasNext } = useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic())

    const hasRecordings = otherRecordings.length > 0

    return (
        <div className="border-t *:not-first:border-t max-h-80 overflow-y-auto">
            {sessionRecordingsResponseLoading && !hasRecordings ? (
                <div className="flex items-center justify-center gap-2 py-12 text-muted">
                    <Spinner textColored />
                    <span>Loading recordings...</span>
                </div>
            ) : !hasRecordings ? (
                <div className="py-2">
                    <EmptyMessage title="No recordings found" description="No recordings match the specified filters" />
                </div>
            ) : (
                <>
                    {otherRecordings.map((recording) => (
                        <div
                            key={recording.id}
                            onClick={(e) => {
                                e.preventDefault()
                                openSessionPlayer(recording)
                            }}
                        >
                            <SessionRecordingPreview recording={recording} selectable={false} />
                        </div>
                    ))}
                    {hasNext && (
                        <div className="p-2">
                            <LemonButton
                                fullWidth
                                type="secondary"
                                size="small"
                                onClick={() => maybeLoadSessionRecordings('older')}
                                loading={sessionRecordingsResponseLoading}
                            >
                                Load more recordings
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

export function ErrorTrackingFiltersWidget({
    toolCallId,
    filters,
}: {
    toolCallId: string
    filters: MaxErrorTrackingSearchResponse | null | undefined
}): JSX.Element {
    const logicProps: MaxErrorTrackingWidgetLogicProps = { toolCallId, filters }

    if (!filters) {
        return (
            <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                <div className="py-2">
                    <EmptyMessage
                        title="Error tracking data unavailable"
                        description="The error tracking search could not be completed"
                    />
                </div>
            </MessageTemplate>
        )
    }

    return (
        <BindLogic logic={maxErrorTrackingWidgetLogic} props={logicProps}>
            <ErrorTrackingFiltersWidgetContent filters={filters} />
        </BindLogic>
    )
}

function ErrorTrackingFiltersWidgetContent({ filters }: { filters: MaxErrorTrackingSearchResponse }): JSX.Element {
    const { activeSceneId } = useValues(sceneLogic)
    const isOnErrorTrackingPage = activeSceneId === Scene.ErrorTracking

    const { issues, hasMore, isLoading } = useValues(maxErrorTrackingWidgetLogic)
    const { loadMoreIssues } = useActions(maxErrorTrackingWidgetLogic)

    const filtersLogic = issueFiltersLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })
    const queryOptionsLogic = issueQueryOptionsLogic({ logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })

    const { setDateRange, setSearchQuery } = useActions(filtersLogic)
    const { setStatus, setOrderBy, setOrderDirection } = useActions(queryOptionsLogic)

    // Automatically apply filters when on the Error Tracking page
    useEffect(() => {
        if (isOnErrorTrackingPage) {
            if (filters.date_from || filters.date_to) {
                setDateRange({ date_from: filters.date_from ?? null, date_to: filters.date_to ?? null })
            }
            if (filters.search_query) {
                setSearchQuery(filters.search_query)
            }
            if (filters.status) {
                setStatus(filters.status as ErrorTrackingQueryStatus)
            }
            if (filters.order_by) {
                setOrderBy(filters.order_by as ErrorTrackingQueryOrderBy)
            }
            if (filters.order_direction) {
                setOrderDirection(filters.order_direction as ErrorTrackingQueryOrderDirection)
            }
        }
    }, [
        isOnErrorTrackingPage,
        setOrderDirection,
        filters.search_query,
        filters.order_direction,
        setOrderBy,
        filters.date_from,
        filters.order_by,
        filters.status,
        setSearchQuery,
        setStatus,
        filters.date_to,
        setDateRange,
    ])

    const buildErrorTrackingUrl = (): string => {
        const params = new URLSearchParams()
        if (filters.status) {
            params.set('status', filters.status)
        }
        if (filters.search_query) {
            params.set('searchQuery', filters.search_query)
        }
        if (filters.date_from) {
            params.set('dateFrom', filters.date_from)
        }
        if (filters.date_to) {
            params.set('dateTo', filters.date_to)
        }
        const query = params.toString()
        return urls.errorTracking() + (query ? `?${query}` : '')
    }

    const hasIssues = issues.length > 0
    const errorTrackingUrl = buildErrorTrackingUrl()

    return (
        <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
            {!isOnErrorTrackingPage && (
                <div className="flex items-center justify-between px-2 pt-2">
                    <span className="text-xs font-semibold text-secondary">Error tracking</span>
                    <LemonButton
                        to={errorTrackingUrl}
                        icon={<IconOpenInNew />}
                        size="xsmall"
                        tooltip="Open in Error tracking"
                    />
                </div>
            )}
            <ErrorTrackingFiltersSummary filters={filters} />
            <div className="border-t">
                {hasIssues ? (
                    <div className="*:not-first:border-t max-h-80 overflow-y-auto">
                        {issues.map((issue: MaxErrorTrackingIssuePreview) => (
                            <ErrorTrackingIssueCard key={issue.id} issue={issue} />
                        ))}
                    </div>
                ) : (
                    <div className="py-2">
                        <EmptyMessage title="No issues found" description="No issues match the specified filters" />
                    </div>
                )}
                {hasMore && (
                    <div className="flex justify-center p-2 border-t">
                        <LemonButton type="tertiary" size="xsmall" onClick={() => loadMoreIssues()} loading={isLoading}>
                            Load more issues
                        </LemonButton>
                    </div>
                )}
            </div>
        </MessageTemplate>
    )
}
