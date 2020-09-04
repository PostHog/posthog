import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { preflightLogic } from './preflightCheckLogic'
import { Row, Col, Space, Card, Button } from 'antd'
import hedgehogBlue from './../../../public/hedgehog-blue.png'
import {
    CheckSquareFilled,
    CloseSquareFilled,
    LoadingOutlined,
    SyncOutlined,
    WarningFilled,
    RocketFilled,
    ApiTwoTone,
} from '@ant-design/icons'
import { volcano, green, red, grey, blue } from '@ant-design/colors'

function PreflightItem(props) {
    /*
    status === undefined -> Item still loading (no positive or negative response yet)
    status === false -> Item not ready (fail to validate)
    status === true -> Item ready (validated)
    */
    const { name, status, caption, failedState } = props
    let textColor

    if (status) textColor = green.primary
    else if (status === false) {
        if (failedState === 'warning') textColor = volcano.primary
        else if (failedState === 'not-required') textColor = grey.primary
        else textColor = red.primary
    } else textColor = grey.primary

    return (
        <Col span={12} style={{ textAlign: 'left', marginBottom: 16, display: 'flex', alignItems: 'center' }}>
            {status === false && failedState !== 'warning' && (
                <CloseSquareFilled style={{ fontSize: 20, color: textColor }} />
            )}
            {status === false && failedState === 'warning' && (
                <WarningFilled style={{ fontSize: 20, color: textColor }} />
            )}

            {status === true && <CheckSquareFilled style={{ fontSize: 20, color: textColor }} />}
            {status !== true && status !== false && <LoadingOutlined style={{ fontSize: 20, color: textColor }} />}
            <span style={{ color: textColor, paddingLeft: 8 }}>
                {name} {caption && status === false && <div style={{ fontSize: 12 }}>{caption}</div>}
            </span>
        </Col>
    )
}

function PreflightCheck() {
    const [state, setState] = useState({})
    const logic = preflightLogic()
    const { preflight } = useValues(logic)
    const { loadPreflight, loadPreflightSuccess } = useActions(logic)
    const isReady = preflight.django && preflight.db && preflight.redis

    const checks = [
        {
            id: 'database',
            name: 'Database (Postgres)',
            status: preflight.db,
        },
        {
            id: 'backend',
            name: 'Backend server (Django)',
            status: preflight.django,
        },
        {
            id: 'redis',
            name: 'Queue processing (Redis)',
            status: preflight.redis,
        },
        {
            id: 'frontend',
            name: 'Frontend built (Webpack)',
            status: true, // If this code is run, the front-end is already built
        },
        {
            id: 'tls',
            name: 'SSL/TLS certificate',
            status: window.location.protocol === 'https:',
            caption:
                state.mode === 'Experimentation'
                    ? 'Not required for development or testing'
                    : 'Install before ingesting real user data',
            failedState: state.mode === 'Experimentation' ? 'not-required' : 'warning',
        },
    ]

    const runChecks = () => {
        // Clear the previous result first and add the timeout to show the loading animation
        loadPreflightSuccess({})
        setTimeout(() => loadPreflight(), 1000)
    }

    const handleModeChange = (mode) => {
        setState({ ...state, mode })
        if (mode) {
            runChecks()
            localStorage.setItem('preflightMode', mode)
        } else {
            localStorage.removeItem('preflightMode')
        }
    }

    const handlePreflightFinished = () => {
        window.location.href = '/signup'
    }

    useEffect(() => {
        const mode = localStorage.getItem('preflightMode')
        if (mode) handleModeChange(mode)
    }, [])

    return (
        <>
            <Space direction="vertical" className="space-top" style={{ width: '100%' }}>
                <h1 className="title text-center" style={{ marginBottom: 0 }}>
                    Welcome to PostHog!
                </h1>
                <div className="page-caption text-center">Understand your users. Build a better product.</div>
            </Space>
            <Col xs={24} style={{ margin: '32px 16px' }}>
                <h2 className="subtitle text-center space-top">
                    We're&nbsp;glad to&nbsp;have you&nbsp;here! Let's&nbsp;get&nbsp;you started with&nbsp;PostHog.
                </h2>
            </Col>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'column' }}>
                    <img src={hedgehogBlue} style={{ maxHeight: '100%' }} />
                    <p>Got any PostHog questions?</p>
                    <Button type="default" data-attr="support" data-source="preflight">
                        <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                            Find support
                        </a>
                    </Button>
                    <div className="breadcrumbs space-top">
                        <span className="selected">Preflight check</span> &gt; Event capture &gt; Team setup
                    </div>
                </div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'flex-start',
                        margin: '0 32px',
                        flexDirection: 'column',
                        paddingTop: 32,
                    }}
                >
                    <Card style={{ width: 600, width: '100%' }}>
                        <Row style={{ display: 'flex', justifyContent: 'space-between', lineHeight: '32px' }}>
                            {!state.mode && <b style={{ fontSize: 16 }}>Select preflight mode</b>}
                            {state.mode && (
                                <>
                                    <b style={{ fontSize: 16 }}>
                                        <span>
                                            <span
                                                style={{ color: blue.primary, cursor: 'pointer' }}
                                                onClick={() => handleModeChange(null)}
                                            >
                                                Select preflight mode
                                            </span>{' '}
                                            &gt; {state.mode}
                                        </span>
                                    </b>
                                    <Button
                                        type="default"
                                        data-attr="preflight-refresh"
                                        icon={<SyncOutlined />}
                                        onClick={() => window.location.reload()}
                                        disabled={Object.keys(preflight).length === 0}
                                    >
                                        Refresh
                                    </Button>
                                </>
                            )}
                        </Row>
                        {!state.mode && (
                            <div>
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
                            </div>
                        )}
                        <div
                            className="text-center"
                            style={{ padding: '24px 0', display: 'flex', justifyContent: 'center', maxWidth: 533 }}
                        >
                            {!state.mode && (
                                <>
                                    <Button
                                        type="default"
                                        data-attr="preflight-experimentation"
                                        onClick={() => handleModeChange('Experimentation')}
                                        icon={<ApiTwoTone />}
                                    >
                                        Just experimenting
                                    </Button>
                                    <Button
                                        type="primary"
                                        style={{ marginLeft: 16 }}
                                        data-attr="preflight-live"
                                        onClick={() => handleModeChange('Live')}
                                        icon={<RocketFilled />}
                                    >
                                        Live implementation
                                    </Button>
                                </>
                            )}

                            {state.mode && (
                                <>
                                    <Row>
                                        {checks.map((item) => (
                                            <PreflightItem key={item.id} {...item} />
                                        ))}
                                    </Row>
                                </>
                            )}
                        </div>

                        <div style={{ fontSize: 12, textAlign: 'center' }}>
                            We will not enforce some security requirements in experimentation mode.
                        </div>
                    </Card>
                    {state.mode && (
                        <>
                            <div className="space-top text-center">
                                {isReady ? (
                                    <b style={{ color: green.primary }}>All systems go!</b>
                                ) : (
                                    <b>Checks in progress…</b>
                                )}
                            </div>
                            <div className="space-top text-center" style={{ marginBottom: 64 }}>
                                <Button
                                    type="primary"
                                    data-attr="preflight-complete"
                                    data-source={state.mode}
                                    disabled={!isReady}
                                    onClick={handlePreflightFinished}
                                >
                                    Continue
                                </Button>
                            </div>
                        </>
                    )}
                </div>
            </Row>
        </>
    )
}

export default PreflightCheck
