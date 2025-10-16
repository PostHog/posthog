import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { IconRabbit, IconSearch, IconTortoise } from '@posthog/icons'
import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import { SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS } from 'lib/constants'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import { SettingsBar, SettingsButton, SettingsMenu } from 'scenes/session-recordings/components/PanelSettings'
import { PlayerInspectorButton } from 'scenes/session-recordings/player/player-meta/PlayerInspectorButton'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

function SetPlaybackSpeed(): JSX.Element {
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
                active: speed === speedToggle && speedToggle !== 1,
                status: speed === speedToggle ? 'danger' : 'default',
            }))}
            label={`Speed ${speed}x`}
        />
    )
}

function InspectDOM(): JSX.Element {
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

function TTLWarning(): JSX.Element | null {
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const lowTtl =
        sessionPlayerMetaData?.recording_ttl &&
        sessionPlayerMetaData.recording_ttl <= SESSION_RECORDINGS_TTL_WARNING_THRESHOLD_DAYS

    useEffect(() => {
        if (lowTtl) {
            posthog.capture('recording viewed with very low TTL', sessionPlayerMetaData)
        }
    }, [sessionPlayerMetaData, lowTtl])

    if (!lowTtl) {
        return null
    }

    return (
        <div className="font-medium">
            <LemonButton
                status="danger"
                size="xsmall"
                className={cn('rounded-[0px]')}
                data-attr="recording-ttl-dialog"
                onClick={() => {
                    LemonDialog.open({
                        title: 'Recording about to expire',
                        description: (
                            <span>
                                This recording will expire in{' '}
                                <strong>{sessionPlayerMetaData.recording_ttl} days</strong>. If you wish to keep it
                                around, you should add it to a collection.
                                <br />
                                Refer to{' '}
                                <Link
                                    to="https://posthog.com/docs/session-replay/data-retention"
                                    disableClientSideRouting
                                    disableDocsPanel
                                    target="_blank"
                                >
                                    this page
                                </Link>{' '}
                                for more information about data retention in Session Replay.
                            </span>
                        ),
                    })
                }}
                noPadding
            >
                This recording will expire in {sessionPlayerMetaData.recording_ttl} days
            </LemonButton>
        </div>
    )
}

export function PlayerMetaTopSettings(): JSX.Element {
    const {
        logicProps: { noInspector },
        hoverModeIsEnabled,
        showPlayerChrome,
    } = useValues(sessionRecordingPlayerLogic)
    const { setPause, openHeatmap } = useActions(sessionRecordingPlayerLogic)

    return (
        <div
            className={cn(
                hoverModeIsEnabled
                    ? 'absolute top-full left-0 right-0 z-10 transition-all duration-25 ease-in-out'
                    : '',
                hoverModeIsEnabled && showPlayerChrome
                    ? 'opacity-100 pointer-events-auto'
                    : hoverModeIsEnabled
                      ? 'opacity-0 pointer-events-none'
                      : ''
            )}
        >
            <SettingsBar border="top">
                <div className="flex w-full justify-between items-center gap-0.5">
                    <div className="flex flex-row gap-0.5 h-full items-center">
                        <SetPlaybackSpeed />
                    </div>

                    <div>
                        <TTLWarning />
                    </div>

                    <div className="flex flex-row gap-0.5">
                        <SettingsButton
                            size="xsmall"
                            icon={<IconHeatmap />}
                            onClick={() => {
                                setPause()
                                openHeatmap()
                            }}
                            label="View heatmap"
                            tooltip="Use the HTML from this point in the recording as the background for your heatmap data"
                        />
                        {noInspector ? null : <InspectDOM />}
                        {noInspector ? null : <PlayerInspectorButton />}
                    </div>
                </div>
            </SettingsBar>
        </div>
    )
}
