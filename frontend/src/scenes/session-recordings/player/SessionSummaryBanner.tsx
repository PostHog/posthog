import clsx from 'clsx'
import { useValues } from 'kea'
import { useState } from 'react'

import { IconAIText, IconCollapse, IconExpand } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { SessionSummaryComponent } from './sidebar/PlayerSidebarSessionSummary'

export function SessionSummaryBanner(): JSX.Element | null {
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { sessionSummary } = useValues(playerMetaLogic(logicProps))
    const [isExpanded, setIsExpanded] = useState(false)

    // Don't show in fullscreen mode
    if (isFullScreen) {
        return null
    }

    // Don't show if no summary
    if (!sessionSummary?.session_outcome?.description) {
        return null
    }

    const isSuccess = sessionSummary.session_outcome.success

    return (
        <div className="border-b">
            <button
                className={clsx(
                    'flex items-center gap-2 w-full px-3 py-2 text-left text-sm cursor-pointer hover:bg-primary-alt-highlight transition-colors',
                    isSuccess === false ? 'bg-danger-highlight' : 'bg-surface-primary'
                )}
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <IconAIText className="text-muted shrink-0" />
                <span className="flex-1">{sessionSummary.session_outcome.description}</span>
                <LemonTag type="warning" size="small">
                    BETA
                </LemonTag>
                {isExpanded ? (
                    <IconCollapse className="text-muted shrink-0" />
                ) : (
                    <IconExpand className="text-muted shrink-0" />
                )}
            </button>
            {isExpanded && (
                <div className="px-3 py-2 border-t bg-surface-primary max-h-80 overflow-y-auto">
                    <SessionSummaryComponent.Segments sessionSummary={sessionSummary} />
                </div>
            )}
        </div>
    )
}
