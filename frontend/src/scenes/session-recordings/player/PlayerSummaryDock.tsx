import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sessionRecordingEventUsageLogic } from '../sessionRecordingEventUsageLogic'
import { playerMetaLogic } from './player-meta/playerMetaLogic'
import { sessionSummaryProgressLogic } from './player-meta/sessionSummaryProgressLogic'
import { LoadingTimer, SessionSummary, SummarizationProgressView } from './PlayerSummaryViews'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

const COLLAPSED_HEIGHT = 44
const DEFAULT_EXPANDED_HEIGHT = 480
const MIN_EXPANDED_HEIGHT = 120
const MAX_EXPANDED_HEIGHT = 800

export function PlayerSummaryDock(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { logicProps, sessionRecordingId, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const {
        sessionSummary,
        sessionSummaryLoading,
        summarizationProgress,
        sessionSummaryError,
        sessionSummaryHasRetried,
        summaryDisabledReason,
    } = useValues(playerMetaLogic(logicProps))
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))
    const { openBySessionId } = useValues(sessionSummaryProgressLogic)
    const { setSummaryOpen } = useActions(sessionSummaryProgressLogic)
    const { reportAISessionSummaryViewed } = useActions(sessionRecordingEventUsageLogic)

    const dockRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'player-summary-dock',
        placement: 'top',
        containerRef: dockRef,
    }
    const { desiredSize, isResizeInProgress } = useValues(resizerLogic(resizerProps))

    const isEnabled = featureFlags[FEATURE_FLAGS.REPLAY_VIDEO_BASED_SUMMARIZATION]
    const hasSummary = !!sessionSummary
    const isOpen = !!openBySessionId[sessionRecordingId]
    const setIsOpen = (open: boolean): void => setSummaryOpen(sessionRecordingId, open)
    const expandedHeight = Math.max(
        MIN_EXPANDED_HEIGHT,
        Math.min(MAX_EXPANDED_HEIGHT, desiredSize ?? DEFAULT_EXPANDED_HEIGHT)
    )

    useEffect(() => {
        if (sessionRecordingId && isOpen) {
            reportAISessionSummaryViewed(sessionRecordingId, 'dock')
        }
    }, [sessionRecordingId, isOpen, reportAISessionSummaryViewed])

    if (!isEnabled) {
        return null
    }

    const hasContentToExpand = hasSummary || sessionSummaryLoading || !!sessionSummaryError

    return (
        <div
            ref={dockRef}
            className={clsx(
                'relative border-t bg-surface-primary overflow-hidden flex flex-col',
                !isResizeInProgress && 'transition-[max-height] duration-300 ease-out'
            )}
            style={{ maxHeight: isOpen ? expandedHeight : COLLAPSED_HEIGHT }}
            data-attr="player-summary-dock"
        >
            {isOpen && <Resizer {...resizerProps} />}
            <div className="flex items-center justify-between h-11 px-3 shrink-0">
                {hasSummary || sessionSummaryLoading ? (
                    <div className="flex items-center gap-2 font-semibold">
                        <IconMagicWand className="text-primary" />
                        AI summary
                    </div>
                ) : (
                    <LemonButton
                        size="small"
                        type="primary"
                        icon={<IconMagicWand />}
                        disabledReason={summaryDisabledReason}
                        onClick={() => {
                            summarizeSession()
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
                        <>
                            {sessionSummaryHasRetried && (
                                <LemonBanner type="warning" className="mb-2">
                                    <div className="text-sm font-normal">
                                        Transient error generating the summary. Retrying...
                                    </div>
                                </LemonBanner>
                            )}
                            {summarizationProgress ? (
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
                            )}
                        </>
                    ) : sessionSummaryError ? (
                        <LemonBanner
                            type="error"
                            action={{
                                children: 'Try again',
                                onClick: () => summarizeSession(),
                            }}
                        >
                            <div className="text-sm font-normal">
                                <strong>Summary failed.</strong> {sessionSummaryError}
                            </div>
                        </LemonBanner>
                    ) : hasSummary ? (
                        <SessionSummary />
                    ) : null}
                </div>
            )}
        </div>
    )
}
