import { Col, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMeta } from 'scenes/session-recordings/player/PlayerMeta'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlayerConsole } from 'scenes/session-recordings/player/PlayerConsole'
import React from 'react'
import { SessionRecordingTab } from '~/types'

const { TabPane } = Tabs

export function PlayerSidebarV2(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingLogic)
    const { setTab } = useActions(sessionRecordingLogic)
    const sessionConsoleEnabled = featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    return (
        <Col className="player-sidebar">
            <div className="player-meta">
                <PlayerMeta />
            </div>
            <div className="player-events">
                {!sessionConsoleEnabled ? (
                    <PlayerEvents />
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
                            <PlayerEvents />
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
                            <PlayerConsole />
                        </TabPane>
                    </Tabs>
                )}
            </div>
        </Col>
    )
}

export function PlayerSidebarV3(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingLogic)
    const sessionConsoleEnabled = !!featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]

    return (
        <Col className="player-sidebar">
            <div className="player-events">
                {sessionConsoleEnabled && tab === SessionRecordingTab.CONSOLE ? <PlayerConsole /> : <PlayerEvents />}
            </div>
        </Col>
    )
}
