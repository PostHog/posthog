import React from 'react'
import { useValues, useActions } from 'kea'
import { preflightLogic } from './logic'
import { Row, Col, Space, Card, Button } from 'antd'
import hedgehogBlue from 'public/hedgehog-blue.png'
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
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/sceneLogic'

interface PreflightItemInterface {
    name: string
    status: boolean
    caption?: string
    failedState?: 'warning' | 'not-required'
}

interface CheckInterface extends PreflightItemInterface {
    id: string
}

function PreflightItem({ name, status, caption, failedState }: PreflightItemInterface): JSX.Element {
    /*
    status === undefined -> Item still loading (no positive or negative response yet)
    status === false -> Item not ready (fail to validate)
    status === true -> Item ready (validated)
    */
    let textColor: string | undefined
    const { preflightLoading } = useValues(preflightLogic)

    if (status) {
        textColor = green.primary
    } else if (status === false) {
        if (failedState === 'warning') {
            textColor = volcano.primary
        } else if (failedState === 'not-required') {
            textColor = grey.primary
        } else {
            textColor = red.primary
        }
    } else {
        textColor = grey.primary
    }

    const icon = (): JSX.Element => {
        if (preflightLoading) {
            return <LoadingOutlined style={{ fontSize: 20, color: textColor }} />
        }
        if (status) {
            return <CheckSquareFilled style={{ fontSize: 20, color: textColor }} />
        } else {
            if (failedState === 'warning') {
                return <WarningFilled style={{ fontSize: 20, color: textColor }} />
            } else {
                return <CloseSquareFilled style={{ fontSize: 20, color: textColor }} />
            }
        }
    }

    return (
        <Col span={12} style={{ textAlign: 'left', marginBottom: 16, display: 'flex', alignItems: 'center' }}>
            {icon()}
            <span style={{ color: textColor, paddingLeft: 8 }}>
                {name}{' '}
                {caption && status === false && (
                    <div data-attr="caption" style={{ fontSize: 12 }}>
                        {caption}
                    </div>
                )}
            </span>
        </Col>
    )
}

export function PreflightCheck(): JSX.Element {
    const { preflight, preflightLoading, preflightMode } = useValues(preflightLogic)
    const { setPreflightMode } = useActions(preflightLogic)
    const isReady =
        preflight &&
        preflight.django &&
        preflight.db &&
        preflight.redis &&
        preflight.celery &&
        (preflightMode === 'experimentation' || preflight.plugins)

    const checks = [
        {
            id: 'database',
            name: 'Database (Postgres)',
            status: preflight?.db,
        },
        {
            id: 'backend',
            name: 'Backend server (Django)',
            status: preflight?.django,
        },
        {
            id: 'redis',
            name: 'Cache & queue (Redis)',
            status: preflight?.redis,
        },
        {
            id: 'celery',
            name: 'Background jobs (Celery)',
            status: preflight?.celery,
        },
        {
            id: 'plugins',
            name: 'Plugin server (Node)',
            status: preflight?.plugins,
            caption: preflightMode === 'experimentation' ? 'Required in production environments' : '',
            failedState: preflightMode === 'experimentation' ? 'warning' : 'error',
        },
        {
            id: 'frontend',
            name: 'Frontend build (Webpack)',
            status: true, // If this code is ran, the front-end is already built
        },
        {
            id: 'tls',
            name: 'SSL/TLS certificate',
            status: window.location.protocol === 'https:',
            caption:
                preflightMode === 'experimentation'
                    ? 'Not required for development or testing'
                    : 'Install before ingesting real user data',
            failedState: preflightMode === 'experimentation' ? 'not-required' : 'warning',
        },
    ] as CheckInterface[]

    const handlePreflightFinished = (): void => {
        router.actions.push(urls.signup())
    }

    return (
        <div style={{ minHeight: '100vh' }}>
            <Space direction="vertical" className="space-top" style={{ width: '100%', paddingLeft: 32 }}>
                <PageHeader title="Welcome to PostHog!" caption="Understand your users. Build a better product." />
            </Space>
            <Col xs={24} style={{ margin: '0 16px' }}>
                <h2 className="subtitle text-center space-top">
                    We're glad to have you here! Let's get you started with PostHog.
                </h2>
            </Col>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'column' }}>
                    <img src={hedgehogBlue} style={{ maxHeight: '100%', width: 320 }} />
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
                    <Card style={{ width: '100%' }}>
                        <Row style={{ display: 'flex', justifyContent: 'space-between', lineHeight: '32px' }}>
                            {!preflightMode ? (
                                <b style={{ fontSize: 16 }}>Select preflight mode</b>
                            ) : (
                                <>
                                    <b style={{ fontSize: 16 }}>
                                        <span>
                                            <span
                                                style={{ color: blue.primary, cursor: 'pointer' }}
                                                onClick={() => setPreflightMode(null)}
                                            >
                                                Select preflight mode
                                            </span>{' '}
                                            &gt; {capitalizeFirstLetter(preflightMode)}
                                        </span>
                                    </b>
                                    <Button
                                        type="default"
                                        data-attr="preflight-refresh"
                                        icon={<SyncOutlined />}
                                        onClick={() => window.location.reload()}
                                        disabled={preflightLoading || !preflight}
                                    >
                                        Refresh
                                    </Button>
                                </>
                            )}
                        </Row>
                        {!preflightMode && (
                            <div>
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
                            </div>
                        )}
                        <div
                            className="text-center"
                            style={{ padding: '24px 0', display: 'flex', justifyContent: 'center', maxWidth: 533 }}
                        >
                            {!preflightMode && (
                                <>
                                    <Button
                                        type="default"
                                        data-attr="preflight-experimentation"
                                        onClick={() => setPreflightMode('experimentation')}
                                        icon={<ApiTwoTone />}
                                    >
                                        Just experimenting
                                    </Button>
                                    <Button
                                        type="primary"
                                        style={{ marginLeft: 16 }}
                                        data-attr="preflight-live"
                                        onClick={() => setPreflightMode('live')}
                                        icon={<RocketFilled />}
                                    >
                                        Live implementation
                                    </Button>
                                </>
                            )}

                            {preflightMode && (
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
                    {preflightMode && (
                        <>
                            <div className="space-top text-center" data-attr="preflightStatus">
                                {isReady ? (
                                    <b style={{ color: green.primary }}>All systems go!</b>
                                ) : (
                                    <b>Checks in progress…</b>
                                )}
                            </div>
                            <div className="text-center" style={{ marginBottom: 64 }}>
                                <Button
                                    type="primary"
                                    data-attr="preflight-complete"
                                    data-source={preflightMode}
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
        </div>
    )
}

export default PreflightCheck
