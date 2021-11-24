import './PlayerMeta.scss'
import React from 'react'
import { Col, Row, Skeleton, Space } from 'antd'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/components/ProfilePicture'
import { useValues } from 'kea'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { metaLogic } from 'scenes/session-recordings/player/metaLogic'
import { formatDisplayPercentage } from 'scenes/funnels/funnelUtils'
import { TZLabel } from 'lib/components/TimezoneAware'

export function PlayerMeta(): JSX.Element {
    const { sessionPerson, description, resolution, scale, meta, loading } = useValues(metaLogic)

    return (
        <Col className="player-meta-container">
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
                            {meta.startTime && <TZLabel time={dayjs(meta.startTime)} />}
                        </span>
                    )}
                </Col>
            </Row>
            <Row className="player-meta-other" align="middle" justify="start">
                <Row className="player-meta-other-description">
                    {loading ? <Skeleton title={false} active paragraph={{ rows: 1 }} /> : <span>{description}</span>}
                </Row>
                <Row className="player-meta-other-resolution mt-05">
                    {loading ? (
                        <Skeleton title={false} active paragraph={{ rows: 1, width: '100%' }} />
                    ) : (
                        <span>
                            {resolution ? (
                                <>
                                    Resolution: {resolution.width} x {resolution.height} (
                                    {formatDisplayPercentage(scale)}%)
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
