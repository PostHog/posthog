import { Col, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMetaV2 } from 'scenes/session-recordings/player/PlayerMeta'
import { PlayerEvents } from 'scenes/session-recordings/player/list/PlayerEvents'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlayerConsole } from 'scenes/session-recordings/player/list/PlayerConsole'
import React from 'react'
import { SessionRecordingTab } from '~/types'
import { PlayerList } from 'scenes/session-recordings/player/list/PlayerList'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

const { TabPane } = Tabs

export function PlayerInspectorV2(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingLogic)
    const { setTab } = useActions(sessionRecordingLogic)
    const sessionConsoleEnabled = featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    return (
        <Col className="player-sidebar">
            <div className="player-meta">
                <PlayerMetaV2 />
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

export function PlayerInspectorV3(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sessionRecordingLogic)
    const sessionConsoleEnabled = !!featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    const currentTab = sessionConsoleEnabled ? tab : SessionRecordingTab.EVENTS

    return (
        <Col className="player-sidebar">
            <div className="player-list">
                <PlayerList
                    tab={currentTab}
                    row={{
                        content: function renderContent(record) {
                            if (currentTab === SessionRecordingTab.CONSOLE) {
                                return <>"CONSOLE"</>
                            }
                            return (
                                <PropertyKeyInfo
                                    className="font-medium"
                                    value={record.event}
                                    disableIcon
                                    disablePopover
                                    ellipsis={true}
                                    style={{ maxWidth: 150 }}
                                />
                            )
                        },
                    }}
                />
            </div>
        </Col>
    )
}
