import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { PLAYBACK_SPEEDS, sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Col, Row, Tabs } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { PlayerMeta } from './PlayerMeta'
import { Console } from './Console'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { NetworkRequests } from 'scenes/session-recordings/player/NetworkRequests'

export function SessionRecordingPlayerV2(): JSX.Element {
    const { togglePlayPause, seekForward, seekBackward, setSpeed, setRootFrame } =
        useActions(sessionRecordingPlayerLogic)
    const { isSmallScreen } = useValues(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame])

    const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>): void => {
        // Don't trigger keydown evens if in input box
        if ((event.target as HTMLInputElement)?.matches('input')) {
            return
        }
        if (event.key === ' ') {
            togglePlayPause()
            event.preventDefault()
        } else if (event.key === 'ArrowLeft') {
            seekBackward()
        } else if (event.key === 'ArrowRight') {
            seekForward()
        } else {
            // Playback speeds shortcuts
            for (let i = 0; i < PLAYBACK_SPEEDS.length; i++) {
                if (event.key === (i + 1).toString()) {
                    setSpeed(PLAYBACK_SPEEDS[i])
                }
            }
        }
    }

    return (
        <Col className="session-player-v2" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} />
                </div>
                {!isSmallScreen && <PlayerSidebar />}
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerController />
            </Row>
            {isSmallScreen && <PlayerSidebar />}
        </Col>
    )
}

const { TabPane } = Tabs

function PlayerSidebar(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { orderedConsoleLogs, sessionNetworkRequests } = useValues(sessionRecordingLogic)
    const { reportRecordingConsoleViewed, reportRecordingNetworkRequestsViewed } = useActions(eventUsageLogic)
    const sessionConsoleEnabled = featureFlags[FEATURE_FLAGS.SESSION_CONSOLE]
    const sessionNetworkRequestsEnabled = featureFlags[FEATURE_FLAGS.SESSION_NETWORK_REQUESTS]
    return (
        <Col className="player-sidebar">
            <div className="player-meta">
                <PlayerMeta />
            </div>
            <div className="player-events">
                {sessionConsoleEnabled || sessionNetworkRequestsEnabled ? (
                    <Tabs
                        data-attr="event-details"
                        defaultActiveKey="events"
                        style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
                        tabBarStyle={{ margin: 0, marginBottom: 8 }}
                        onChange={(key) => {
                            if (key === 'console') {
                                reportRecordingConsoleViewed(orderedConsoleLogs.length)
                            }
                            if (key === 'network-requests') {
                                reportRecordingNetworkRequestsViewed(sessionNetworkRequests?.length || 0)
                            }
                        }}
                    >
                        <TabPane tab="Events" key="events">
                            <PlayerEvents />
                        </TabPane>
                        {sessionConsoleEnabled && (
                            <TabPane
                                tab={
                                    <div>
                                        Console (beta)
                                        <Tooltip title="While console logs are in beta, only 150 logs are displayed.">
                                            <InfoCircleOutlined style={{ marginLeft: 6 }} />
                                        </Tooltip>
                                    </div>
                                }
                                key="console"
                            >
                                <Console />
                            </TabPane>
                        )}
                        {sessionNetworkRequestsEnabled && (
                            <TabPane
                                tab={
                                    <div>
                                        Network Requests (beta)
                                        <Tooltip title="Network requests are in beta, not all requests are captured.">
                                            <InfoCircleOutlined style={{ marginLeft: 6 }} />
                                        </Tooltip>
                                    </div>
                                }
                                key="network-requests"
                            >
                                <NetworkRequests />
                            </TabPane>
                        )}
                    </Tabs>
                ) : (
                    <PlayerEvents />
                )}
            </div>
        </Col>
    )
}
