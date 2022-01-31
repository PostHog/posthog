import React from 'react'
import { useValues, useActions } from 'kea'
import { preflightLogic } from './logic'
import { Row, Col, Card, Button, Steps } from 'antd'
import suprisedHog from 'public/surprised-hog.png'
import posthogLogo from 'public/posthog-logo.png'
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
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'

const { Step } = Steps

interface PreflightItemInterface {
    name: string
    status: boolean
    caption?: string
    failedState?: 'warning' | 'not-required'
}

interface CheckInterface extends PreflightItemInterface {
    id: string
}

export const scene: SceneExport = {
    component: PreflightCheck,
    logic: preflightLogic,
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
            <Row
                style={{
                    display: 'flex',
                    justifyContent: 'center',
                    paddingTop: 32,
                    paddingBottom: 32,
                    backgroundColor: '#eeefe9',
                }}
            >
                <img src={posthogLogo} style={{ width: 157, height: 30 }} />
            </Row>
            <Row style={{ display: 'flex', justifyContent: 'center', paddingBottom: 16 }}>
                <PageHeader title="Lets get started..." />
            </Row>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ width: 960 }}>
                    <Steps current={0}>
                        <Step title="Preflight check" subTitle="1 min" description="Prepare your instance" />
                        <Step
                            title="Event capture"
                            subTitle="15 mins"
                            description="Set up your app to capture events"
                        />
                        <Step
                            title="Setup your team"
                            subTitle="5 mins"
                            description="Invite your team and start discovering insights"
                        />
                    </Steps>
                </div>
            </Row>
            <Row style={{ display: 'flex', justifyContent: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', flexDirection: 'column' }}>
                    <img src={suprisedHog} style={{ maxHeight: '100%', width: 320 }} />
                    <p>Any questions?</p>
                    <Button type="default" data-attr="support" data-source="preflight">
                        <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                            Get support
                        </a>
                    </Button>
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
                                <b style={{ fontSize: 16 }}>Select launch mode</b>
                            ) : (
                                <>
                                    <b style={{ fontSize: 16 }}>
                                        <span>
                                            <span
                                                style={{ color: blue.primary, cursor: 'pointer' }}
                                                onClick={() => setPreflightMode(null)}
                                            >
                                                Select launch mode
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
                            <div>We're excited to have you here. What's your plan for this installation?</div>
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
                                        size="large"
                                        onClick={() => setPreflightMode('experimentation')}
                                        icon={<ApiTwoTone />}
                                    >
                                        Just playing
                                    </Button>
                                    <Button
                                        type="primary"
                                        style={{ marginLeft: 16 }}
                                        size="large"
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
