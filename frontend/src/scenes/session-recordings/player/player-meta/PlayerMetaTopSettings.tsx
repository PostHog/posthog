import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useMemo } from 'react'

import { IconBottomPanel, IconRabbit, IconSearch, IconTortoise } from '@posthog/icons'
import { LemonMenuItems, Link } from '@posthog/lemon-ui'

import { SettingsButton, SettingsMenu } from 'lib/components/PanelSettings/PanelSettings'
import { SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import {
    ModesWithInteractions,
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { SessionRecordingType } from '~/types'

export function SetPlaybackSpeed(): JSX.Element {
    const { speed, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { setSpeed } = useActions(sessionRecordingPlayerLogic)
    return (
        <SettingsMenu
            icon={
                speed === 0.5 ? (
                    <IconTortoise className="text-lg" style={{ stroke: 'currentColor', strokeWidth: '0.5' }} />
                ) : (
                    <IconRabbit className="text-lg" style={{ stroke: 'currentColor', strokeWidth: '0.5' }} />
                )
            }
            data-attr="session-recording-speed-select"
            items={PLAYBACK_SPEEDS.map((speedToggle) => ({
                label: (
                    <div className="flex w-full deprecated-space-x-2 justify-between">
                        <span>{speedToggle}x</span>
                        <span>({humanFriendlyDuration(sessionPlayerData.durationMs / speedToggle / 1000)})</span>
                    </div>
                ),
                onClick: () => setSpeed(speedToggle),
                'data-attr': `speed-${speedToggle}x`,
                active: speed === speedToggle && speedToggle !== 1,
                status: speed === speedToggle ? 'danger' : 'default',
            }))}
            label={`Speed ${speed}x`}
        />
    )
}

export function InspectDOM(): JSX.Element {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { openExplorer } = useActions(sessionRecordingPlayerLogic)

    return (
        <SettingsButton
            title="Inspect the DOM as it was at this moment in the session. Analyze the structure and elements captured during the recording."
            label="Inspect DOM"
            data-attr="explore-dom"
            onClick={openExplorer}
            disabledReason={
                sessionPlayerMetaData?.snapshot_source === 'mobile' ? 'Only available for web recordings' : undefined
            }
            icon={<IconSearch />}
        />
    )
}

function useLowTtlMeta(): { sessionPlayerMetaData: SessionRecordingType | null; lowTtl: boolean } {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const lowTtl =
        !!sessionPlayerMetaData?.recording_ttl &&
        sessionPlayerMetaData.recording_ttl <= SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS
    return { sessionPlayerMetaData, lowTtl }
}

export function useReportLowTtlViewed(): void {
    const { sessionPlayerMetaData, lowTtl } = useLowTtlMeta()
    useEffect(() => {
        if (lowTtl) {
            posthog.capture('recording viewed with very low TTL', sessionPlayerMetaData)
        }
    }, [sessionPlayerMetaData, lowTtl])
}

export function TTLWarning(): JSX.Element | null {
    const { sessionPlayerMetaData, lowTtl } = useLowTtlMeta()

    if (!lowTtl || !sessionPlayerMetaData) {
        return null
    }

    return (
        <div className="text-xs text-danger">
            Expires in {sessionPlayerMetaData.recording_ttl} days.{' '}
            <Link to={urls.settings('project-replay', 'replay-retention')} data-attr="player-ttl-open-settings">
                Extend retention
            </Link>
        </div>
    )
}

export function usePlayerChromeMenuItems(): LemonMenuItems {
    const {
        logicProps: { mode },
        playerControlsOverlay,
    } = useValues(sessionRecordingPlayerLogic)
    const { setPlayerControlsOverlay, setPause, openHeatmap } = useActions(sessionRecordingPlayerLogic)
    const { modalContext } = useValues(sessionPlayerModalLogic)

    const showControlsLayoutToggle = !!mode && ModesWithInteractions.includes(mode)
    const showHeatmap = modalContext?.type !== 'heatmap-background-selection'

    return useMemo(
        () => [
            showControlsLayoutToggle && {
                label: playerControlsOverlay ? 'Pin controls below recording' : 'Float controls over recording',
                icon: <IconBottomPanel />,
                onClick: () => setPlayerControlsOverlay(!playerControlsOverlay),
                'data-attr': 'toggle-player-controls-overlay',
            },
            showHeatmap && {
                label: 'Use as heatmap background',
                icon: <IconHeatmap />,
                onClick: () => {
                    setPause()
                    openHeatmap()
                },
                'data-attr': 'player-view-heatmap',
            },
        ],
        [showControlsLayoutToggle, playerControlsOverlay, showHeatmap, setPlayerControlsOverlay, setPause, openHeatmap]
    )
}
