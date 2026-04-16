import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { playerMetaLogic } from './player-meta/playerMetaLogic'
import { sessionSummaryProgressLogic } from './player-meta/sessionSummaryProgressLogic'
import { LoadingTimer, SessionSummary, SummarizationProgressView } from './PlayerSummaryViews'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

const EXPANDED_MAX_HEIGHT = 480

export function PlayerSummaryDock(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { logicProps, sessionRecordingId, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary, sessionSummaryLoading, summarizationProgress, summaryDisabledReason } = useValues(
        playerMetaLogic(logicProps)
    )
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))
    const { openBySessionId } = useValues(sessionSummaryProgressLogic)
    const { setSummaryOpen } = useActions(sessionSummaryProgressLogic)
    const { reportAISessionSummaryViewed } = useActions(sessionRecordingEventUsageLogic)

    const isEnabled =
        featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY] || featureFlags[FEATURE_FLAGS.MAX_SESSION_SUMMARIZATION]
    const hasSummary = !!sessionSummary
    const isOpen = !!openBySessionId[sessionRecordingId]
    const setIsOpen = (open: boolean): void => setSummaryOpen(sessionRecordingId, open)

    useEffect(() => {
        if (sessionRecordingId && isOpen) {
            reportAISessionSummaryViewed(sessionRecordingId, 'dock')
        }
    }, [sessionRecordingId, isOpen, reportAISessionSummaryViewed])

    if (!isEnabled) {
        return null
    }

    const hasContentToExpand = hasSummary || sessionSummaryLoading

    return (
        <div
            className="border-t bg-surface-primary overflow-hidden transition-[max-height] duration-300 ease-out flex flex-col"
            style={{ maxHeight: isOpen ? EXPANDED_MAX_HEIGHT : 44 }}
            data-attr="player-summary-dock"
        >
            <div className="flex items-center justify-between h-11 px-3 shrink-0">
                {hasSummary ? (
                    <div className="flex items-center gap-2 font-semibold">
                        <IconMagicWand className="text-primary" />
                        AI summary
                    </div>
                ) : (
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconMagicWand />}
                        loading={sessionSummaryLoading}
                        disabledReason={summaryDisabledReason}
                        onClick={() => {
                            if (!sessionSummaryLoading) {
                                summarizeSession()
                            }
                            setIsOpen(true)
                        }}
                        data-attr="load-session-summary"
                    >
                        Use AI to summarize this session
                    </LemonButton>
                )}
                {(hasContentToExpand || isOpen) && (
                    <LemonButton
                        size="small"
                        icon={<IconChevronDown className={isOpen ? '' : 'rotate-180'} />}
                        onClick={() => setIsOpen(!isOpen)}
                        tooltip={isOpen ? 'Collapse' : 'Expand'}
                        aria-label={isOpen ? 'Collapse summary' : 'Expand summary'}
                    />
                )}
            </div>
            {isOpen && (
                <div className="flex-1 overflow-y-auto px-3 pb-3">
                    {sessionSummaryLoading ? (
                        summarizationProgress ? (
                            <SummarizationProgressView
                                progress={summarizationProgress}
                                sessionDurationMs={sessionPlayerData?.durationMs}
                            />
                        ) : (
                            <div className="flex items-center justify-between">
                                <div>
                                    Researching the session... <Spinner />
                                </div>
                                <div className="flex items-center gap-1 ml-auto">
                                    <LoadingTimer />
                                </div>
                            </div>
                        )
                    ) : hasSummary ? (
                        <SessionSummary />
                    ) : null}
                </div>
            )}
        </div>
    )
}
