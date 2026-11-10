import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'

import { aiConsentLogic } from '~/layout/ai/aiConsentLogic'

import { PersonIcon } from 'products/persons/frontend/components/PersonDisplay'
import { asDisplay } from 'products/persons/frontend/person-utils'
import { QuillSummarizeRecordingBar } from 'products/replay_vision/frontend/components/QuillSummarizeRecordingBar'
import { useVisionSurfaceShown } from 'products/replay_vision/frontend/utils/useVisionSurfaceShown'

import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import { DebugModeBanner } from './DebugModeBanner'
import { RecordingCommentsList } from './RecordingCommentsList'
import { RecordingTitleBlock } from './RecordingTitleBlock'
import { WatchPanelSections } from './WatchPanelSections'
import { WatchPanelSectionsWithObservations } from './WatchPanelSectionsWithObservations'

export const WATCH_PANEL_COLLAPSED_SIZE = '2.5rem'

export function WatchPanel(): JSX.Element | null {
    const { sessionRecordingId } = useValues(sessionRecordingPlayerLogic)
    const vision = useVisionSurfaceShown()
    const { debugMode, watchDebugDock, watchPanelCollapsed } = useValues(playerSettingsLogic)
    const { setWatchPanelCollapsed } = useActions(playerSettingsLogic)
    const { dataProcessingAccepted } = useValues(aiConsentLogic)
    if (!sessionRecordingId) {
        return null
    }
    if (watchPanelCollapsed) {
        return <WatchPanelCollapsedBar />
    }
    const debugDocked = debugMode && watchDebugDock === 'bottom'

    return (
        <div
            data-quill
            className="flex flex-col gap-3 px-1 pt-2 pb-1.5 text-foreground isolate h-full min-h-0 overflow-y-auto [&>*]:shrink-0"
            data-attr="watch-panel"
        >
            <DebugModeBanner />
            <RecordingTitleBlock
                actions={vision ? <QuillSummarizeRecordingBar /> : undefined}
                trailingActions={
                    <Button
                        size="icon"
                        onClick={() => setWatchPanelCollapsed(true)}
                        tooltip="Collapse"
                        aria-label="Collapse"
                        data-attr="watch-panel-collapse"
                    >
                        <IconChevronDown />
                    </Button>
                }
            />
            {vision && dataProcessingAccepted ? (
                <WatchPanelSectionsWithObservations sessionId={sessionRecordingId} debug={debugDocked} />
            ) : (
                <WatchPanelSections debug={debugDocked} />
            )}
            <RecordingCommentsList sessionId={sessionRecordingId} />
        </div>
    )
}

function WatchPanelCollapsedBar(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPerson } = useValues(playerMetaLogic(logicProps))
    const { setWatchPanelCollapsed } = useActions(playerSettingsLogic)

    return (
        <div
            data-quill
            className="flex items-center gap-2 px-2 h-full min-w-0 text-foreground"
            data-attr="watch-panel-collapsed"
        >
            {sessionPerson && <PersonIcon person={sessionPerson} size="sm" className="mr-0 shrink-0" />}
            <span className="text-sm font-medium truncate ph-no-capture">
                {sessionPerson ? asDisplay(sessionPerson) : 'Unknown user'}
            </span>
            <Button
                size="icon"
                className="ml-auto"
                onClick={() => setWatchPanelCollapsed(false)}
                tooltip="Expand"
                aria-label="Expand"
                data-attr="watch-panel-collapse"
            >
                <IconChevronDown className="rotate-180" />
            </Button>
        </div>
    )
}
