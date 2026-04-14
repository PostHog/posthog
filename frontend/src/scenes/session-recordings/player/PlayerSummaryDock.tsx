import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconChevronDown, IconMagicWand } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { playerMetaLogic } from './player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { SessionSummary } from './sidebar/PlayerSidebarSessionSummary'

const EXPANDED_MAX_HEIGHT = 480

export function PlayerSummaryDock(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary, sessionSummaryLoading } = useValues(playerMetaLogic(logicProps))
    const { summarizeSession } = useActions(playerMetaLogic(logicProps))

    const isEnabled =
        featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY] || featureFlags[FEATURE_FLAGS.MAX_SESSION_SUMMARIZATION]
    const hasSummary = !!sessionSummary

    const [isOpen, setIsOpen] = useState(false)

    // Auto-expand when a summary arrives or loading starts — but only on transition.
    // Using the hook deps lets the user collapse afterward without re-opening on every render.
    useEffect(() => {
        if (hasSummary || sessionSummaryLoading) {
            setIsOpen(true)
        }
    }, [hasSummary, sessionSummaryLoading])

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
                        onClick={() => {
                            if (!sessionSummaryLoading) {
                                summarizeSession()
                            }
                            setIsOpen(true)
                        }}
                        data-attr="player-summary-dock-summarize"
                    >
                        Summarize this session
                    </LemonButton>
                )}
                {hasContentToExpand && (
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
                    {hasContentToExpand ? (
                        <SessionSummary />
                    ) : (
                        <div className="flex items-center gap-2 text-secondary text-sm">
                            <Spinner /> Generating summary…
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
