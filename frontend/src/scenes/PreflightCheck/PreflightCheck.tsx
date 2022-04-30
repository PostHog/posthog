import React from 'react'
import { useValues, useActions } from 'kea'
import { LoadingOutlined } from '@ant-design/icons'
import { PreflightItemInterface, preflightLogic } from './preflightLogic'
import './PreflightCheck.scss'
import { capitalizeFirstLetter } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'
import { WelcomeLogo } from 'scenes/authentication/WelcomeLogo'
import { LemonButton } from 'lib/components/LemonButton'
import { CheckCircleOutlined, ErrorIcon, RefreshIcon, WarningIcon } from 'lib/components/icons'
import clsx from 'clsx'

export const scene: SceneExport = {
    component: PreflightCheck,
    logic: preflightLogic,
}

function PreflightItem({ name, status, caption }: PreflightItemInterface): JSX.Element {
    const { preflightLoading } = useValues(preflightLogic)

    const icon = (): JSX.Element => {
        if (preflightLoading) {
            return <LoadingOutlined style={{ color: 'var(--primary)' }} />
        }
        if (status === 'verified') {
            return <CheckCircleOutlined />
        } else if (status === 'warning' || status === 'optional') {
            return <WarningIcon />
        }
        return <ErrorIcon />
    }

    return (
        <div
            className={clsx(
                'preflight-item',
                preflightLoading && 'loading',
                status === 'verified' && 'success',
                status === 'warning' && 'warning',
                status === 'optional' && 'optional',
                status === 'error' && 'error'
            )}
        >
            <div className="icon-container">{icon()}</div>
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
                    {capitalizeFirstLetter(preflightLoading ? 'verifying' : status)}
                </p>
            </div>
        </div>
    )
}

export function PreflightCheck(): JSX.Element {
    const { preflight, preflightLoading, preflightMode, isReady, checks } = useValues(preflightLogic)
    const { setPreflightMode, handlePreflightFinished } = useActions(preflightLogic)

    return (
        <div className="bridge-page preflight-check-container">
            <div>
                <WelcomeLogo view="preflight-check" />
                <div className="preflight-box">
                    {!preflightMode ? (
                        <>
                            <p className="title-text">Select a launch mode</p>
                            <p className="secondary-text">
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
                            </p>
                            <LemonButton
                                type="primary"
                                fullWidth
                                center
                                className="mt-05"
                                size="large"
                                data-attr="preflight-experimentation"
                                onClick={() => setPreflightMode('experimentation')}
                            >
                                Just experimenting
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                center
                                type="secondary"
                                className="mt-05"
                                size="large"
                                data-attr="preflight-live"
                                onClick={() => setPreflightMode('live')}
                            >
                                Live implementation
                            </LemonButton>
                        </>
                    ) : (
                        <>
                            <p className="title-text">Verify implementation</p>
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

                            {checks.map((item) => (
                                <PreflightItem key={item.id} {...item} />
                            ))}

                            <LemonButton
                                fullWidth
                                center
                                type="secondary"
                                className="mt"
                                size="large"
                                data-attr="preflight-refresh"
                                onClick={() => window.location.reload()}
                                disabled={preflightLoading || !preflight}
                            >
                                <RefreshIcon />
                                <span style={{ paddingLeft: 8 }}>Verify requirements</span>
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                center
                                type={isReady ? 'primary' : 'secondary'}
                                className="mt-05"
                                size="large"
                                data-attr="preflight-complete"
                                onClick={handlePreflightFinished}
                            >
                                {`Continue${isReady ? '' : ' without verifying'}`}
                            </LemonButton>
                        </>
                    )}
                    {(!preflightMode || preflightMode === 'experimentation') && (
                        <div>
                            <div className="divider" />
                            <p className="text-muted text-center">
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
