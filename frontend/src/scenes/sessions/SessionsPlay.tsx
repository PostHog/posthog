import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Player, PlayerRef, findCurrent } from '@posthog/react-rrweb-player'
import { Card, Col, Input, Row, Skeleton, Tag } from 'antd'
import {
    UserOutlined,
    FieldTimeOutlined,
    PlusOutlined,
    SyncOutlined,
    LaptopOutlined,
    MobileOutlined,
    TabletOutlined,
} from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { colorForString } from 'lib/utils'
import { Loading } from 'lib/utils'
import { sessionsPlayLogic } from './sessionsPlayLogic'
import { IconExternalLink } from 'lib/components/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

import './Sessions.scss'
import './SessionsPlayer.scss'

function formatDuration(milliseconds: number): string {
    const multipliers: Array<[number, string]> = [
        [24 * 60 * 60 * 1000, 'day'],
        [60 * 60 * 1000, 'hour'],
        [60 * 1000, 'minute'],
    ]
    for (const [multiplier, identifier] of multipliers) {
        if (milliseconds > multiplier) {
            return `${Math.round(milliseconds / multiplier)} ${identifier}`
        }
    }
    return `${Math.round(milliseconds / 1000)} second`
}

function DeviceIcon({ width }: { width: number }): JSX.Element {
    if (width <= 475) {
        return <MobileOutlined />
    } else if (width > 475 && width < 860) {
        return <TabletOutlined />
    }
    return <LaptopOutlined />
}

export function SessionsPlay(): JSX.Element {
    const {
        session,
        sessionPlayerData,
        sessionPlayerDataLoading,
        loadingNextRecording,
        sessionDate,
        addingTagShown,
        addingTag,
        tags,
        tagsLoading,
        eventIndex,
        showNext,
        showPrev,
        shownPlayerEvents,
        shouldLoadSessionEvents,
    } = useValues(sessionsPlayLogic)
    const { toggleAddingTagShown, setAddingTag, createTag, goToNext, goToPrevious, loadSessionEvents } =
        useActions(sessionsPlayLogic)
    const addTagInput = useRef<Input>(null)

    const [playerTime, setCurrentPlayerTime] = useState(0)
    const playerRef = useRef<PlayerRef>(null)
    const [pageEvent] = useMemo(() => eventIndex.getPageMetadata(playerTime), [eventIndex, playerTime])
    const [recordingMetadata] = useMemo(() => eventIndex.getRecordingMetadata(playerTime), [eventIndex, playerTime])
    const activeIndex = useMemo(() => findCurrent(playerTime, shownPlayerEvents), [shownPlayerEvents, playerTime])[1]

    const isLoadingSession = sessionPlayerDataLoading || loadingNextRecording
    const isLoadingEvents = isLoadingSession || shouldLoadSessionEvents

    useEffect(() => {
        if (addingTagShown && addTagInput.current) {
            addTagInput.current.focus()
        }
    }, [addingTagShown])

    useEffect(() => {
        if (shouldLoadSessionEvents && session) {
            loadSessionEvents(session)
        }
    }, [session])

    const seekEvent = (time: number): void => {
        setCurrentPlayerTime(time)
        playerRef.current?.seek(time)
    }

    return (
        <div className="session-player">
            <Row gutter={16} style={{ height: '100%' }}>
                <Col span={18} style={{ paddingRight: 0 }}>
                    <div className="mb-05" style={{ display: 'flex' }}>
                        {isLoadingSession ? (
                            <Skeleton paragraph={{ rows: 0 }} active />
                        ) : (
                            <>
                                {pageEvent ? (
                                    <>
                                        <b>Current URL:</b>
                                        <span className="url-info ml-05">{pageEvent.href}</span>
                                        <CopyToClipboardInline explicitValue={pageEvent.href} isValueSensitive>
                                            &nbsp;
                                        </CopyToClipboardInline>
                                    </>
                                ) : null}
                                {recordingMetadata && (
                                    <span style={{ marginLeft: 'auto' }}>
                                        <b>Resolution: </b>
                                        <DeviceIcon width={recordingMetadata.width} /> {recordingMetadata.resolution}
                                    </span>
                                )}
                            </>
                        )}
                    </div>
                    <div className="player-container">
                        {isLoadingSession ? (
                            <Loading />
                        ) : (
                            <span className="ph-no-capture">
                                <Player
                                    ref={playerRef}
                                    events={sessionPlayerData?.snapshots || []}
                                    onPlayerTimeChange={setCurrentPlayerTime}
                                    onNext={showNext ? goToNext : undefined}
                                    onPrevious={showPrev ? goToPrevious : undefined}
                                />
                            </span>
                        )}
                    </div>
                </Col>
                <Col span={6} className="sidebar" style={{ paddingLeft: 16 }}>
                    <Card className="card-elevated">
                        <h3 className="l3">Session Information</h3>
                        {isLoadingSession ? (
                            <div>
                                <Skeleton paragraph={{ rows: 3 }} active />
                            </div>
                        ) : (
                            <>
                                <div className="mb-05">
                                    <FieldTimeOutlined /> {formatDuration(eventIndex.getDuration())} session on{' '}
                                    {sessionDate}
                                </div>
                                <div>
                                    <UserOutlined style={{ marginRight: 4 }} />
                                    <Link
                                        to={`/person/${encodeURIComponent(
                                            sessionPlayerData?.person?.distinct_ids[0] || ''
                                        )}`}
                                        className="ph-no-capture"
                                        target="_blank"
                                        style={{ display: 'inline-flex', alignItems: 'center' }}
                                    >
                                        <span style={{ marginRight: 4 }}>{sessionPlayerData?.person?.name}</span>
                                        <IconExternalLink />
                                    </Link>
                                </div>
                                <div className="mt" style={{ display: 'none' }}>
                                    <div>
                                        <b>Tags</b>
                                    </div>
                                    {tags.map((tag, index) => {
                                        return (
                                            <Tag
                                                key={index}
                                                color={colorForString(tag)}
                                                closable
                                                className="tag-wrapper"
                                            >
                                                {tag}
                                            </Tag>
                                        )
                                    })}
                                    <span className="tag-wrapper" style={{ display: 'inline-flex' }}>
                                        <Tag
                                            onClick={toggleAddingTagShown}
                                            data-attr="button-add-tag"
                                            style={{
                                                cursor: 'pointer',
                                                borderStyle: 'dashed',
                                                backgroundColor: '#ffffff',
                                                display: addingTagShown ? 'none' : 'initial',
                                            }}
                                        >
                                            <PlusOutlined /> New Tag
                                        </Tag>
                                        <Input
                                            type="text"
                                            size="small"
                                            onBlur={toggleAddingTagShown}
                                            ref={addTagInput}
                                            style={{ width: 78, display: !addingTagShown ? 'none' : 'flex' }}
                                            value={addingTag}
                                            onChange={(e) => setAddingTag(e.target.value)}
                                            onPressEnter={createTag}
                                            disabled={tagsLoading}
                                            prefix={tagsLoading ? <SyncOutlined spin /> : null}
                                        />
                                    </span>
                                </div>
                            </>
                        )}
                    </Card>
                    <div className="mt" />
                    <Card className="card-elevated">
                        <h3 className="l3">Event timeline</h3>
                        <p className="text-muted text-small">
                            Click on an item to jump to that point in the recording.
                        </p>
                        {isLoadingEvents ? (
                            <div>
                                <Skeleton paragraph={{ rows: 6 }} active />
                            </div>
                        ) : (
                            <div className="timeline">
                                <div className="line" />
                                <div className="timeline-items">
                                    {shownPlayerEvents.map(({ playerTime: time, color, text }, index) => (
                                        <div className={index == activeIndex ? 'current' : undefined} key={index}>
                                            <Tag onClick={() => seekEvent(time)} color={color}>
                                                {text}
                                            </Tag>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
