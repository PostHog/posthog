import React, { useState, useEffect } from 'react'
import { useValues, useActions } from 'kea'
import { preflightLogic } from './preflightCheckLogic'
import { Row, Col, Space, Card, Button } from 'antd'
import hedgehogBlue from './../../../public/hedgehog-blue.jpg'
import {
    CheckSquareFilled,
    CloseSquareFilled,
    LoadingOutlined,
    SyncOutlined,
    WarningFilled,
    RocketFilled,
    ApiTwoTone,
} from '@ant-design/icons'

function PreflightItem(props) {
    /*
    status === undefined -> Item still loading (no positive or negative response yet)
    status === false -> Item not ready (fail to validate)
    status === true -> Item ready (validated)
    */
    const { name, status, caption, failedState } = props
    let textColor

    if (status) textColor = '#28A745'
    else if (status === false) {
        if (failedState === 'warning') textColor = '#F7A501'
        else if (failedState === 'not-required') textColor = '#666666'
        else textColor = '#F96132'
    } else textColor = '#666666'

    return (
        <Col span={12} style={{ textAlign: 'left', marginTop: 16, display: 'flex', alignItems: 'center' }}>
            {status === false && failedState !== 'warning' && (
                <CloseSquareFilled style={{ fontSize: 20, color: textColor }} />
            )}
            {status === false && failedState === 'warning' && (
                <WarningFilled style={{ fontSize: 20, color: textColor }} />
            )}

            {status === true && <CheckSquareFilled style={{ fontSize: 20, color: textColor }} />}
            {status !== true && status !== false && <LoadingOutlined style={{ fontSize: 20, color: textColor }} />}
            <span style={{ color: textColor, paddingLeft: 8 }}>
                {name}{' '}
                {caption && status === false && <div style={{ fontSize: 12, fontWeight: 'bold' }}>{caption}</div>}
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
            name: 'Frontend built (Node)',
            status: true, // If this code is run, the front-end is already built
        },
        {
            id: 'tls',
            name: 'SSL/TLS certificate',
            status: window.location.protocol === 'https:',
            caption:
                state.mode === 'Experimentation'
                    ? 'Not required for testing / experimenting'
                    : 'Required, but may be installed later',
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
        window.location.href = '/setup_admin'
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
                            Get Help
                        </a>
                    </Button>
                    <div className="breadcrumbs space-top">
                        <span className="selected">Pre-flight check</span> &gt; Event capture &gt; Team setup
                    </div>
                </div>
                <div
                    style={{
                        display: 'flex',
                        justifyContent: 'flex-start',
                        marginLeft: 32,
                        flexDirection: 'column',
                        paddingTop: 32,
                    }}
                >
                    <Card style={{ width: 600, width: '100%' }}>
                        <Row style={{ marginBottom: 16 }}>
                            {!state.mode && <b style={{ fontSize: 16 }}>Preflight check</b>}
                            {state.mode && (
                                <>
                                    <b style={{ fontSize: 16 }}>
                                        <span>
                                            <span
                                                style={{ color: '#1890ff', cursor: 'pointer' }}
                                                onClick={() => handleModeChange(null)}
                                            >
                                                Select preflight mode
                                            </span>{' '}
                                            &gt; {state.mode}
                                        </span>
                                    </b>
                                    <Button
                                        type="default"
                                        style={{ position: 'absolute', right: 16 }}
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
                            style={{ padding: 32, display: 'flex', justifyContent: 'center', maxWidth: 600 }}
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

                        <div style={{ fontSize: 12 }}>
                            We will not enforce some security requirements in experimentation mode.
                        </div>
                    </Card>
                    {state.mode && (
                        <>
                            <div className="space-top text-center">
                                {!isReady && <b>Please review the items above before continuing</b>}
                                {isReady && (
                                    <b style={{ color: '#28A745' }}>
                                        Congratulations! Looks like your infrastructure is ready!
                                    </b>
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
