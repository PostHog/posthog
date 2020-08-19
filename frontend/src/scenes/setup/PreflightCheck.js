import React from 'react'
import { Row, Col, Space, Card, Button } from 'antd'
import hedgehogBlue from './../../../public/hedgehog-blue.jpg'

function PreflightCheck() {
    return (
        <>
            <Space direction="vertical" className="space-top" style={{ width: '100%' }}>
                <h1 className="title text-center" style={{ marginBottom: 0 }}>
                    Welcome to PostHog!
                </h1>
                <div className="page-caption text-center">Understand your users. Build a better product.</div>
            </Space>
            <Col xs={24} style={{ marginTop: 60 }}>
                <h2 className="subtitle text-center space-top">
                    We're glad to have you here! We'll now guide you to setting up PostHog.
                </h2>
            </Col>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'column' }}>
                    <img src={hedgehogBlue} style={{ maxHeight: '100%' }} />
                    <Button type="default" data-attr="support" data-source="preflight">
                        <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                            Support
                        </a>
                    </Button>
                    <div className="breadcrumbs space-top">
                        <span className="selected">Pre-flight check</span> &gt; Event capture &gt; Team setup
                    </div>
                </div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'center',
                        marginLeft: 32,
                        flexDirection: 'column',
                        paddingTop: 32,
                    }}
                >
                    <Card style={{ width: 600, width: '100%' }}>
                        <b style={{ fontSize: 16 }}>Preflight check</b>
                        <div>
                            Tell us what you plan to do with this installation to make sure your infrastructure is ready
                        </div>
                        <div className="text-center" style={{ padding: 32 }}>
                            <Button type="default" data-attr="preflight-experimenting">
                                🧪 Just experimenting
                            </Button>
                            <Button type="primary" style={{ marginLeft: 16 }} data-attr="preflight-live">
                                🚀 Live implementation
                            </Button>
                        </div>

                        <div style={{ fontSize: 12 }}>
                            We will not enforce some security requirements on experimentation mode.
                        </div>
                    </Card>
                    <div className="space-top text-center">
                        <b>Please review the items above before continuing</b>
                    </div>
                    <div className="space-top text-center">
                        <Button type="primary" data-attr="preflight-complete" disabled>
                            Continue
                        </Button>
                    </div>
                </div>
            </Row>
        </>
    )
}

export default PreflightCheck
