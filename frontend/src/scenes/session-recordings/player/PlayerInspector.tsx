import { Col, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMetaV2 } from 'scenes/session-recordings/player/PlayerMeta'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlayerConsole } from 'scenes/session-recordings/player/PlayerConsole'
import React from 'react'
import { SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'

const { TabPane } = Tabs

export function PlayerInspectorV2({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingDataLogic({ sessionRecordingId }))
    const { setTab } = useActions(sessionRecordingDataLogic({ sessionRecordingId }))
    const sessionConsoleEnabled = featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    return (
        <Col className="player-sidebar">
            <div className="player-meta">
                <PlayerMetaV2 sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <div className="player-events">
                {!sessionConsoleEnabled ? (
                    <PlayerEvents sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                ) : (
                    <Tabs
                        data-attr="event-details"
                        activeKey={tab}
                        style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
                        tabBarStyle={{ margin: 0, marginBottom: 8 }}
                        onChange={(tab) => {
                            setTab(tab as SessionRecordingTab)
                        }}
                    >
                        <TabPane tab="Events" key={SessionRecordingTab.EVENTS}>
                            <PlayerEvents sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                        </TabPane>
                        <TabPane
                            tab={
                                <Tooltip title="While console logs are in BETA, only 150 logs are displayed.">
                                    <div>
                                        Console
                                        <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
                                            BETA
                                        </LemonTag>
                                    </div>
                                </Tooltip>
                            }
                            key={SessionRecordingTab.CONSOLE}
                        >
                            <PlayerConsole sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                        </TabPane>
                    </Tabs>
                )}
            </div>
        </Col>
    )
}

export function PlayerInspectorV3({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingDataLogic({ sessionRecordingId, playerKey }))
    const sessionConsoleEnabled = !!featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]

    return (
        <Col className="player-sidebar">
            <div className="player-events">
                {sessionConsoleEnabled && tab === SessionRecordingTab.CONSOLE ? (
                    <PlayerConsole sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                ) : (
                    <PlayerEvents sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                )}
            </div>
        </Col>
    )
}
