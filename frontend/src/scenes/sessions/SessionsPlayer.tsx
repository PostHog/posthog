import React from 'react'
import './Sessions.scss'
import { Card, Col, Row } from 'antd'
import { Loading } from 'lib/utils'
import { AppleOutlined, ChromeOutlined, PushpinOutlined, UserOutlined, FieldTimeOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'

export default function SessionsPlayer(): JSX.Element {
    // TODO: TEMPORARY VALUES FOR TESTING
    const sessionPlayerDataLoading = false

    return (
        <div className="session-player">
            <Row gutter={16} style={{ height: '100%' }}>
                <Col span={18}>
                    <div className="mb-05">
                        <b>Current URL: </b> https://posthog.com/docs
                        <span className="float-right">
                            <ChromeOutlined /> Chrome on <AppleOutlined /> macOS (1400 x 600)
                        </span>
                    </div>
                    <div className="ph-no-capture" style={{ height: '90%', position: 'relative' }}>
                        {sessionPlayerDataLoading ? (
                            <Loading />
                        ) : (
                            <div style={{ height: '100%', backgroundColor: '#C4C4C4' }} />
                        )}
                    </div>
                </Col>
                <Col span={6}>
                    <Card className="card-elevated">
                        <h3 className="l3">Session #2191</h3>
                        <div className="mb-05">
                            <FieldTimeOutlined /> 3 minute session on Oct 19
                        </div>
                        <div className="mb-05">
                            <PushpinOutlined /> Paris, FR
                        </div>
                        <div>
                            <UserOutlined style={{ marginRight: 4 }} />
                            <Link to="" target="_blank">
                                marius@posthog.com
                            </Link>
                        </div>
                    </Card>
                    <div className="mt" />
                    <Card className="card-elevated">
                        <h3 className="l3">Event timeline</h3>
                    </Card>
                </Col>
            </Row>
        </div>
    )
}
