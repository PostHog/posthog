import React from 'react'
import { useValues, useActions } from 'kea'
import { Row, Col } from 'antd'
import { LoadingOutlined, WarningFilled } from '@ant-design/icons'
import { router } from 'kea-router'
import { preflightLogic } from './preflightLogic'
import './PreflightCheck.scss'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'
import { SceneExport } from 'scenes/sceneTypes'
import { WelcomeHedgehog } from 'lib/components/WelcomeHedgehog/WelcomeHeadgehog'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { LemonButton } from 'lib/components/LemonButton'
import { CheckCircleOutlined, CloseCircleOutlined, IconChevronRight, RefreshIcon } from 'lib/components/icons'

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

function PreflightItem({ name, status, failedState }: PreflightItemInterface): JSX.Element {
    /*
    status === undefined -> Item still loading (no positive or negative response yet)
    status === false -> Item not ready (fail to validate)
    status === true -> Item ready (validated)
    */
    let textColor: string
    const { preflightLoading } = useValues(preflightLogic)

    if (status) {
        textColor = 'var(--success)'
    } else if (status === false) {
        if (failedState === 'warning') {
            textColor = 'var(--warning)'
        } else if (failedState === 'not-required') {
            textColor = 'var(--border-dark)'
        } else {
            textColor = 'var(--danger)'
        }
    } else {
        textColor = 'var(--border-dark)'
    }

    const icon = (): JSX.Element => {
        if (preflightLoading) {
            return <LoadingOutlined style={{ fontSize: 20, color: textColor }} />
        }
        if (status) {
            return <CheckCircleOutlined style={{ fontSize: 20, color: textColor }} />
        } else {
            if (failedState === 'warning') {
                return <WarningFilled style={{ fontSize: 20, color: textColor }} />
            } else {
                return <CloseCircleOutlined style={{ fontSize: 20, color: textColor }} />
            }
        }
    }

    return (
        <Col span={12} style={{ textAlign: 'left', marginBottom: 16 }}>
            <div style={{ alignItems: 'center', display: 'flex' }}>
                {icon()}
                <span style={{ color: textColor, paddingLeft: 8 }}>{name}</span>
            </div>
        </Col>
    )
}

export function PreflightCheck(): JSX.Element {
    const { preflight, preflightLoading, preflightMode } = useValues(preflightLogic)
    const { setPreflightMode, loadPreflight } = useActions(preflightLogic)
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
                    ? 'Not required for experimentation mode'
                    : 'Install before ingesting real user data',
            failedState: preflightMode === 'experimentation' ? 'not-required' : 'warning',
        },
    ] as CheckInterface[]

    const handlePreflightFinished = (): void => {
        router.actions.push(urls.signup())
    }

    return (
        <div
            className="bridge-page"
            style={{
                minHeight: '100vh',
                alignItems: 'center',
                justifyContent: 'center',
                display: 'flex',
                flexDirection: 'row',
            }}
        >
            <div className="side-container">
                <WelcomeHedgehog showWelcomeMessage={!preflightMode} />
            </div>
            <div>
                <WelcomeLogo view="preflight-check" />
                <div className="preflight-box">
                    {!preflightMode ? (
                        <div>
                            <p className="title-text">Select a launch mode</p>
                            <p className="secondary-text">
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
                            </p>
                            <LemonButton
                                type="primary"
                                fullWidth
                                center
                                className="ingestion-btn mb-05"
                                onClick={() => setPreflightMode('experimentation')}
                            >
                                Just experimenting
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                center
                                type="secondary"
                                className="ingestion-btn inverted mb-05"
                                onClick={() => setPreflightMode('live')}
                            >
                                Live implementation
                            </LemonButton>
                        </div>
                    ) : (
                        <div className="preflight">
                            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
                                <a
                                    onClick={() => {
                                        setPreflightMode(null)
                                    }}
                                >
                                    Select a preflight mode
                                </a>
                                <IconChevronRight /> {capitalizeFirstLetter(preflightMode)}
                            </div>
                            {preflightMode && (
                                <>
                                    <Row>
                                        {checks.map((item) => (
                                            <PreflightItem key={item.id} {...item} />
                                        ))}
                                    </Row>
                                </>
                            )}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div>{isReady ? <b>🚀 All systems go!</b> : <b>Checks in progress…</b>}</div>
                                <div style={{ display: 'flex', alignItems: 'center' }}>
                                    <LemonButton onClick={loadPreflight} disabled={preflightLoading || !preflight}>
                                        <RefreshIcon />
                                        <span style={{ paddingLeft: 8 }}>Refresh</span>
                                    </LemonButton>
                                    <LemonButton
                                        style={{ marginLeft: 8 }}
                                        type="primary"
                                        onClick={handlePreflightFinished}
                                        className="ingestion-btn"
                                        disabled={!isReady}
                                    >
                                        Continue
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    )}
                    {(!preflightMode || preflightMode === 'experimentation') && (
                        <div>
                            <div className="divider" />
                            <p className="text-muted">
                                We will not enforce some security requirements in experimentation mode.
                            </p>
                        </div>
                    )}
                </div>
                <div style={{ marginTop: 16, textAlign: 'center' }}>
                    <p className="text-muted">
                        {`Have questions? `}
                        <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                            Visit support
                        </a>
                    </p>
                </div>
            </div>
        </div>
    )
}

export default PreflightCheck
