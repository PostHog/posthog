import { Col, Tabs } from 'antd'
import { useActions, useValues } from 'kea'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { PlayerMetaV2 } from 'scenes/session-recordings/player/PlayerMeta'
import { PlayerEvents } from 'scenes/session-recordings/player/list/PlayerEvents'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { PlayerConsole } from 'scenes/session-recordings/player/list/PlayerConsole'
import React from 'react'
import { SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'
import { PlayerList } from 'scenes/session-recordings/player/list/PlayerList'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { interleave } from 'lib/utils'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import { sharedListLogic } from 'scenes/session-recordings/player/list/sharedListLogic'

const { TabPane } = Tabs

export function PlayerInspectorV2({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { tab } = useValues(sharedListLogic({ sessionRecordingId, playerKey }))
    const { setTab } = useActions(sharedListLogic({ sessionRecordingId, playerKey }))
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
    const { tab } = useValues(sharedListLogic({ sessionRecordingId, playerKey }))
    const sessionConsoleEnabled = !!featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    const currentTab = sessionConsoleEnabled ? tab : SessionRecordingTab.EVENTS

    return (
        <Col className="player-sidebar">
            <div className="player-list">
                <PlayerList
                    sessionRecordingId={sessionRecordingId}
                    playerKey={playerKey}
                    tab={currentTab}
                    row={{
                        status: (record) => {
                            if (record.level === 'match') {
                                return RowStatus.Match
                            }
                            if (currentTab === SessionRecordingTab.EVENTS) {
                                return null
                            }
                            // Below statuses only apply to console logs
                            if (record.level === 'warn') {
                                return RowStatus.Warning
                            }
                            if (record.level === 'log') {
                                return RowStatus.Information
                            }
                            if (record.level === 'error') {
                                return RowStatus.Error
                            }
                            if (record.level === 'error') {
                                return RowStatus.Error
                            }
                            return RowStatus.Information
                        },
                        content: function renderContent(record) {
                            if (currentTab === SessionRecordingTab.CONSOLE) {
                                return (
                                    <div className="font-mono text-xs w-full text-ellipsis">
                                        {interleave(record.previewContent, ' ')}
                                    </div>
                                )
                            }
                            return (
                                <div className="flex flex-row justify-start">
                                    <PropertyKeyInfo
                                        className="font-medium"
                                        value={record.event}
                                        disableIcon
                                        disablePopover
                                        ellipsis={true}
                                        style={{ maxWidth: 150 }}
                                    />
                                </div>
                            )
                        },
                        sideContent: function renderSideContent(record) {
                            if (currentTab === SessionRecordingTab.CONSOLE) {
                                return <div className="font-mono text-xs">{record.traceContent?.[0]}</div>
                            }
                            return null
                        },
                    }}
                />
            </div>
        </Col>
    )
}
