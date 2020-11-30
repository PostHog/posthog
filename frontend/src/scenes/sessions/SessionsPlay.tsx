import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Player, PlayerRef } from 'posthog-react-rrweb-player'
import { Card, Col, Input, Row, Skeleton, Tag } from 'antd'
import {
    AppleOutlined,
    ChromeOutlined,
    UserOutlined,
    FieldTimeOutlined,
    PlusOutlined,
    SyncOutlined,
} from '@ant-design/icons'
import { hot } from 'react-hot-loader/root'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { colorForString } from 'lib/utils'
import { Loading } from 'lib/utils'
import { sessionsPlayLogic } from './sessionsPlayLogic'
import { IconExternalLink } from 'lib/components/icons'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import './Sessions.scss'
import './SessionsPlayer.scss'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export const SessionsPlay = hot(_SessionsPlay)
function _SessionsPlay(): JSX.Element {
    const {
        sessionPlayerData,
        sessionPlayerDataLoading,
        addingTagShown,
        addingTag,
        tags,
        tagsLoading,
        sessionTimestamp,
        eventIndex,
        pageVisitEvents,
    } = useValues(sessionsPlayLogic)
    const { toggleAddingTagShown, setAddingTag, createTag } = useActions(sessionsPlayLogic)
    const addTagInput = useRef<Input>(null)

    const [playerTime, setCurrentPlayerTime] = useState(0)
    const playerRef = useRef<PlayerRef>(null)
    const [pageEvent, atPageIndex] = useMemo(() => eventIndex.getPageMetadata(playerTime), [eventIndex, playerTime])

    useEffect(() => {
        if (addingTagShown && addTagInput.current) {
            addTagInput.current.focus()
        }
    }, [addingTagShown])

    return (
        <div className="session-player">
            <Row gutter={16} style={{ height: '100%' }}>
                <Col span={18} style={{ paddingRight: 0 }}>
                    <div className="mb-05" style={{ display: 'flex' }}>
                        {sessionPlayerDataLoading && <Skeleton paragraph={{ rows: 0 }} active />}

                        {!sessionPlayerDataLoading && (
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
                                {/* TODO: Not implemented */}
                                <span className="float-right" style={{ display: 'none' }}>
                                    <ChromeOutlined /> Chrome on <AppleOutlined /> macOS (1400 x 600)
                                </span>
                            </>
                        )}
                    </div>
                    <div className="ph-no-capture player-container">
                        {sessionPlayerDataLoading ? (
                            <Loading />
                        ) : (
                            <Player
                                ref={playerRef}
                                events={sessionPlayerData?.snapshots || []}
                                onPlayerTimeChange={setCurrentPlayerTime}
                            />
                        )}
                    </div>
                </Col>
                <Col span={6} className="sidebar" style={{ paddingLeft: 16 }}>
                    <Card className="card-elevated">
                        <h3 className="l3">Session Information</h3>
                        {sessionPlayerDataLoading && (
                            <div>
                                <Skeleton paragraph={{ rows: 3 }} active />
                            </div>
                        )}
                        {!sessionPlayerDataLoading && (
                            <>
                                <div className="mb-05" style={{ display: 'none' }}>
                                    {/* TODO: Add session duration information */}
                                    <FieldTimeOutlined /> {sessionTimestamp}
                                </div>
                                {sessionPlayerData?.person && (
                                    <div>
                                        <UserOutlined style={{ marginRight: 4 }} />
                                        <Link
                                            to={`/person/${encodeURIComponent(
                                                sessionPlayerData.person.distinct_ids[0]
                                            )}`}
                                            className={rrwebBlockClass + ' ph-no-capture'}
                                            target="_blank"
                                            style={{ display: 'inline-flex', alignItems: 'center' }}
                                        >
                                            <span style={{ marginRight: 4 }}>{sessionPlayerData.person.name}</span>
                                            <IconExternalLink />
                                        </Link>
                                    </div>
                                )}
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
                        {sessionPlayerDataLoading && (
                            <div>
                                <Skeleton paragraph={{ rows: 6 }} active />
                            </div>
                        )}
                        {!sessionPlayerDataLoading && (
                            <div className="timeline">
                                <div className="line" />
                                <div className="timeline-items">
                                    {pageVisitEvents.map(({ href, playerTime }, index) => (
                                        <div className={index === atPageIndex ? 'current' : undefined} key={index}>
                                            <Tag onClick={() => playerRef.current?.seek(playerTime)}>{href}</Tag>
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
