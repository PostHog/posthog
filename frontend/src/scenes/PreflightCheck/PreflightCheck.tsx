import React from 'react'
import { useValues, useActions } from 'kea'
import { LoadingOutlined } from '@ant-design/icons'
import { PreflightCheckStatus, PreflightItemInterface, preflightLogic } from './preflightLogic'
import './PreflightCheck.scss'
import { capitalizeFirstLetter } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { LemonButton } from 'lib/components/LemonButton'
import {
    IconCheckCircleOutline,
    IconErrorOutline,
    IconUnfoldLess,
    IconUnfoldMore,
    IconRefresh,
    IconWarningAmber,
} from 'lib/components/icons'
import clsx from 'clsx'
import { LemonRow } from 'lib/components/LemonRow'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'

export const scene: SceneExport = {
    component: PreflightCheck,
    logic: preflightLogic,
}

function PreflightCheckIcon({ status, loading }: { status: PreflightCheckStatus; loading?: boolean }): JSX.Element {
    const size = {
        height: '20px',
        width: '20px',
    }
    if (loading) {
        return <LoadingOutlined style={{ color: 'var(--primary)' }} />
    }
    if (status === 'running') {
        return <IconCheckCircleOutline {...size} />
    } else if (status === 'warning' || status === 'optional') {
        return <IconWarningAmber {...size} />
    }
    return <IconErrorOutline {...size} />
}

function PreflightItem({ name, status, caption }: PreflightItemInterface): JSX.Element {
    const { preflightLoading } = useValues(preflightLogic)
    return (
        <div className={clsx('preflight-item', preflightLoading ? 'loading' : status)}>
            <div className="icon-container">
                <PreflightCheckIcon status={status} loading={preflightLoading} />
            </div>
            <div className="central-text-container">
                <p className="check-name">{name}</p>
                {caption && (
                    <p data-attr="caption" className="text-muted">
                        {caption}
                    </p>
                )}
            </div>

            <div className="right-status">
                <p className="status-text" data-attr="status-text">
                    {capitalizeFirstLetter(preflightLoading ? 'checking' : status)}
                </p>
            </div>
        </div>
    )
}

export function PreflightCheck(): JSX.Element {
    const { preflight, preflightLoading, preflightMode, checks, areChecksExpanded, checksSummary } =
        useValues(preflightLogic)
    const { setPreflightMode, handlePreflightFinished, setChecksManuallyExpanded } = useActions(preflightLogic)

    return (
        <div className="bridge-page preflight-check-container">
            <div>
                <WelcomeLogo view="preflight-check" />
                {!preflightMode ? (
                    <>
                        <div className="preflight-box">
                            <p className="title-text">Select a launch mode</p>
                            <p className="secondary-text">
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
                            </p>
                            <LemonButton
                                fullWidth
                                center
                                type="primary"
                                className="mt-05"
                                size="large"
                                data-attr="preflight-live"
                                onClick={() => setPreflightMode('live')}
                            >
                                Live implementation
                            </LemonButton>
                            <LemonButton
                                type="secondary"
                                fullWidth
                                center
                                className="mt-05"
                                size="large"
                                data-attr="preflight-experimentation"
                                onClick={() => setPreflightMode('experimentation')}
                            >
                                Just experimenting
                            </LemonButton>
                            <div className="divider" />
                            <p className="text-muted text-center">
                                We will not enforce some security requirements in experimentation mode.
                            </p>
                        </div>
                        <div style={{ marginTop: 16, textAlign: 'center' }}>
                            <p className="text-muted">
                                {`Have questions? `}
                                <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                                    Visit support
                                </a>
                            </p>
                        </div>
                    </>
                ) : (
                    <>
                        <div className="preflight-box">
                            <p className="title-text">Validate implementation</p>
                            <p className="secondary-text">
                                Need help? Take a look at our{' '}
                                <a
                                    href="https://posthog.com/docs/self-host/deploy/troubleshooting"
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    documentation
                                </a>{' '}
                                or{' '}
                                <a href="https://posthog.com/support" target="_blank" rel="noreferrer">
                                    visit support
                                </a>
                                .
                            </p>

                            <div className="preflight-checks-container">
                                <div className="preflight-check-summary">
                                    <div
                                        className={clsx(
                                            'preflight-summary-icon-container',
                                            preflightLoading ? 'loading' : checksSummary.summaryStatus
                                        )}
                                    >
                                        <PreflightCheckIcon
                                            status={checksSummary.summaryStatus}
                                            loading={preflightLoading}
                                        />
                                    </div>
                                    <div className="preflight-summary-text-container">
                                        <p className="check-summary-header">Validation checks</p>
                                        <p data-attr="caption" className="text-muted check-summary-description">
                                            {checksSummary.summaryString}
                                        </p>
                                    </div>
                                    <LemonButton
                                        size="small"
                                        style={{ fontSize: 20 }}
                                        onClick={() => {
                                            setChecksManuallyExpanded(!areChecksExpanded)
                                        }}
                                    >
                                        {areChecksExpanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                    </LemonButton>
                                </div>
                                <AnimatedCollapsible collapsed={!areChecksExpanded}>
                                    <>
                                        {checks.map((item) => (
                                            <PreflightItem key={item.id} {...item} />
                                        ))}
                                    </>
                                </AnimatedCollapsible>
                                <LemonButton
                                    center
                                    fullWidth
                                    size="large"
                                    data-attr="preflight-refresh"
                                    onClick={() => window.location.reload()}
                                    disabled={preflightLoading || !preflight}
                                    style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0 }}
                                >
                                    <IconRefresh />
                                    <span style={{ paddingLeft: 8 }}>Validate requirements</span>
                                </LemonButton>
                            </div>
                            <div className="divider" />
                            {checksSummary.summaryStatus !== 'down' ? (
                                <LemonButton
                                    fullWidth
                                    center
                                    type="primary"
                                    className="mt-05"
                                    size="large"
                                    data-attr="preflight-complete"
                                    onClick={handlePreflightFinished}
                                >
                                    Continue
                                </LemonButton>
                            ) : (
                                <LemonRow fullWidth center className="mt-05 cannot-continue" size="large">
                                    <p className="text-center text-muted">
                                        All required checks must pass before you can continue
                                    </p>
                                </LemonRow>
                            )}

                            <p className="text-center mt">
                                Validation happens immediately. You can rerun validation checks by clicking{' '}
                                <b>“validate requirements”</b>.
                            </p>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

export default PreflightCheck
