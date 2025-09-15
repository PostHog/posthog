import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconEllipsis, IconHourglass, IconRabbit, IconSearch, IconTortoise } from '@posthog/icons'
import { LemonButton, LemonDialog, Link } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { IconHeatmap } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils'
import { cn } from 'lib/utils/css-classes'
import {
    SettingsBar,
    SettingsButton,
    SettingsMenu,
    SettingsToggle,
} from 'scenes/session-recordings/components/PanelSettings'
import { PlayerInspectorButton } from 'scenes/session-recordings/player/player-meta/PlayerInspectorButton'
import { PlayerMetaBreakpoints } from 'scenes/session-recordings/player/player-meta/PlayerMeta'
import { playerSettingsLogic } from 'scenes/session-recordings/player/playerSettingsLogic'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { playerMetaLogic } from './playerMetaLogic'

const TTL_WARNING_THRESHOLD_DAYS = 10 // days

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

function SkipInactivity(): JSX.Element {
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)

    return (
        <SettingsToggle
            title="Skip inactive parts of the recording"
            label="Skip inactivity"
            active={skipInactivitySetting}
            data-attr="skip-inactivity"
            onClick={() => setSkipInactivitySetting(!skipInactivitySetting)}
            icon={<IconHourglass />}
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
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPlayerMetaData } = useValues(sessionRecordingPlayerLogic)
    const { sessionTTLDays } = useValues(playerMetaLogic(logicProps))

    if (sessionTTLDays === null || sessionTTLDays > TTL_WARNING_THRESHOLD_DAYS) {
        return null
    }
    posthog.capture('recording viewed with very low TTL', sessionPlayerMetaData)

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
                                This recording will expire in <strong>{sessionTTLDays} days</strong>. If you wish to
                                keep it around, you should add it to a collection.
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
                This recording will expire in {sessionTTLDays} days
            </LemonButton>
        </div>
    )
}

export function PlayerMetaTopSettings({ size }: { size: PlayerMetaBreakpoints }): JSX.Element {
    const {
        logicProps: { noInspector },
    } = useValues(sessionRecordingPlayerLogic)
    const { setPause, openHeatmap } = useActions(sessionRecordingPlayerLogic)
    const { skipInactivitySetting } = useValues(playerSettingsLogic)
    const { setSkipInactivitySetting } = useActions(playerSettingsLogic)
    const isSmall = size === 'small'

    const menuItems: LemonMenuItem[] = [
        isSmall
            ? {
                  label: 'Skip inactivity',
                  active: skipInactivitySetting,
                  'data-attr': 'skip-inactivity-in-menu',
                  onClick: () => setSkipInactivitySetting(!skipInactivitySetting),
                  icon: <IconHourglass />,
              }
            : undefined,
    ].filter(Boolean) as LemonMenuItem[]

    return (
        <SettingsBar border="top">
            <div className="flex w-full justify-between items-center gap-0.5">
                <div className="flex flex-row gap-0.5 h-full items-center">
                    <SetPlaybackSpeed />
                    {!isSmall && <SkipInactivity />}
                    {isSmall && (
                        <SettingsMenu
                            icon={<IconEllipsis />}
                            items={menuItems}
                            highlightWhenActive={false}
                            closeOnClickInside={false}
                        />
                    )}
                </div>
                {!isSmall && (
                    <div>
                        <TTLWarning />
                    </div>
                )}
                <div className="flex flex-row gap-0.5">
                    <FlaggedFeature match={true} flag={FEATURE_FLAGS.HEATMAPS_UI}>
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
                    </FlaggedFeature>
                    {noInspector ? null : <InspectDOM />}
                    <PlayerInspectorButton />
                </div>
            </div>
        </SettingsBar>
    )
}
