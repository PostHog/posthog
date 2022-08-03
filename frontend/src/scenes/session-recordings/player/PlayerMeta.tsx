import './PlayerMeta.scss'
import React from 'react'
import { Col, Row, Skeleton, Space } from 'antd'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { useValues } from 'kea'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { TZLabel } from 'lib/components/TimezoneAware'
import { percentage, truncate } from 'lib/utils'
import { LemonDivider } from 'lib/components/LemonDivider'
import { IconWindow } from 'scenes/session-recordings/player/icons'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

export function PlayerMetaV2(): JSX.Element {
    const { sessionPerson, description, resolution, scale, recordingStartTime, loading } = useValues(metaLogic)

    return (
        <Col className="player-meta-container-v2">
            <Row className="player-meta-person" align="middle" justify="space-between" wrap={false}>
                <Row className="player-meta-person-title" align="middle" wrap={false}>
                    {loading ? (
                        <Space>
                            <Skeleton.Avatar active size="small" shape="circle" />
                            <Skeleton title={false} active paragraph={{ rows: 1, width: 160 }} />
                        </Space>
                    ) : (
                        <>
                            <ProfilePicture
                                name={sessionPerson?.name}
                                email={sessionPerson?.properties?.$email}
                                size="md"
                                style={{ marginRight: '0.5rem' }}
                            />
                            <span className="email">
                                <PersonHeader person={sessionPerson} withIcon={false} />
                            </span>
                        </>
                    )}
                </Row>
                <Col>
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: 80 }} />
                    ) : (
                        <span className="time text-muted">
                            {recordingStartTime && <TZLabel time={dayjs(recordingStartTime)} />}
                        </span>
                    )}
                </Col>
            </Row>
            <Row className="player-meta-other" align="middle" justify="start">
                <Row className="player-meta-other-description">
                    {loading ? <Skeleton title={false} active paragraph={{ rows: 1 }} /> : <span>{description}</span>}
                </Row>
                <Row className="player-meta-other-resolution mt-2">
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: '100%' }} />
                    ) : (
                        <span>
                            {resolution ? (
                                <>
                                    Resolution: {resolution.width} x {resolution.height} ({percentage(scale, 1, true)})
                                </>
                            ) : (
                                <>Resolution: ...</>
                            )}
                        </span>
                    )}
                </Row>
            </Row>
        </Col>
    )
}

export function PlayerMetaV3(): JSX.Element {
    const {
        sessionPerson,
        description,
        resolution,
        currentUrl,
        scale,
        currentWindowIndex,
        recordingStartTime,
        loading,
    } = useValues(metaLogic)
    return (
        <div className="player-meta-container-v3">
            <Row className="player-meta-user-section">
                <Col className="player-meta-avatar">
                    {loading ? (
                        <Skeleton.Avatar active size={48} shape="circle" />
                    ) : (
                        <ProfilePicture
                            name={sessionPerson?.name}
                            email={sessionPerson?.properties?.$email}
                            size="xxl"
                        />
                    )}
                </Col>
                <Col className="player-meta-details">
                    <Row className="player-meta-details-top">
                        {loading ? (
                            <Skeleton title={false} active paragraph={{ rows: 1, width: 250 }} />
                        ) : (
                            <Space size={4}>
                                <PersonHeader person={sessionPerson} withIcon={false} noEllipsis={true} />
                                {'·'}
                                <TZLabel
                                    time={dayjs(recordingStartTime)}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                    showPopover={false}
                                />
                            </Space>
                        )}
                    </Row>
                    <Row className="player-meta-details-bottom text-muted">
                        {loading ? (
                            <Skeleton title={false} active paragraph={{ rows: 1, width: 160 }} />
                        ) : (
                            <span>{description}</span>
                        )}
                    </Row>
                </Col>
            </Row>
            <LemonDivider style={{ margin: 0 }} />
            <Row className="player-meta-window-section" justify="space-between" align="middle">
                <Row align="middle">
                    {loading || currentWindowIndex === -1 ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: 250 }} />
                    ) : (
                        <Space size={4} align="center">
                            <IconWindow
                                windowNumber={currentWindowIndex + 1}
                                className="text-muted"
                                style={{ marginRight: '0.25rem' }}
                            />
                            <div className="window-number">Window {currentWindowIndex + 1}</div>
                            {currentUrl && (
                                <>
                                    {'· '}
                                    <a href={currentUrl} target="_blank">
                                        {truncate(currentUrl, 32)}
                                    </a>
                                    <span className="window-url-copy-icon">
                                        <CopyToClipboardInline description="current url" explicitValue={currentUrl} />
                                    </span>
                                </>
                            )}
                        </Space>
                    )}
                </Row>
                <Row align="middle">
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: 250 }} />
                    ) : (
                        <span>
                            {resolution && (
                                <>
                                    Resolution: {resolution.width} x {resolution.height} ({percentage(scale, 1, true)})
                                </>
                            )}
                        </span>
                    )}
                </Row>
            </Row>
        </div>
    )
}
