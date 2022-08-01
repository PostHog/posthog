import './styles.scss'
import React, { useEffect, useRef } from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'
import { Col, Row, Tabs } from 'antd'
import { PlayerMeta } from './PlayerMeta'
import { Console } from './Console'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { sessionRecordingLogic } from '../sessionRecordingLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'

export function useFrameRef(): React.MutableRefObject<HTMLDivElement | null> {
    const { setRootFrame } = useActions(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)
    // Need useEffect to populate replayer on component paint
    useEffect(() => {
        if (frame.current) {
            setRootFrame(frame.current)
        }
    }, [frame])

    return frame
}

export function SessionRecordingPlayer(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    if (featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYER_V3]) {
        return <SessionRecordingPlayerV3 />
    }
    return <SessionRecordingPlayerV2 />
}

export function SessionRecordingPlayerV2(): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic)
    const { isSmallScreen } = useValues(sessionRecordingPlayerLogic)
    const frame = useFrameRef()
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

export function SessionRecordingPlayerV3(): JSX.Element {
    const { handleKeyDown } = useActions(sessionRecordingPlayerLogic)
    const frame = useFrameRef()
    return (
        <Col className="session-player-v3" onKeyDown={handleKeyDown} tabIndex={0} flex={1}>
            <Row className="session-player-body" wrap={false}>
                <div className="player-container ph-no-capture">
                    <PlayerFrame ref={frame} />
                </div>
            </Row>
            <Row className="player-controller" align="middle">
                <PlayerController />
            </Row>
            <PlayerSidebar />
        </Col>
    )
}

const { TabPane } = Tabs

function PlayerSidebar(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { orderedConsoleLogs } = useValues(sessionRecordingLogic)
    const { reportRecordingConsoleViewed } = useActions(eventUsageLogic)
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
                        defaultActiveKey="events"
                        style={{ display: 'flex', flexDirection: 'column', height: '100%' }}
                        tabBarStyle={{ margin: 0, marginBottom: 8 }}
                        onChange={(key) => {
                            if (key === 'console') {
                                reportRecordingConsoleViewed(orderedConsoleLogs.length)
                            }
                        }}
                    >
                        <TabPane tab="Events" key="events">
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
                            key="console"
                        >
                            <Console />
                        </TabPane>
                    </Tabs>
                )}
            </div>
        </Col>
    )
}
