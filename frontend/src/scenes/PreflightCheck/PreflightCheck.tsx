import React from 'react'
import { useValues, useActions } from 'kea'
import { LoadingOutlined } from '@ant-design/icons'
import { PreflightCheckStatus, PreflightItem, preflightLogic } from './preflightLogic'
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
import { LemonDivider } from 'lib/components/LemonDivider'

export const scene: SceneExport = {
    component: PreflightCheck,
    logic: preflightLogic,
}

function PreflightCheckIcon({ status, loading }: { status: PreflightCheckStatus; loading?: boolean }): JSX.Element {
    if (loading) {
        return <LoadingOutlined style={{ color: 'var(--primary)' }} />
    }
    if (status === 'validated') {
        return <IconCheckCircleOutline />
    } else if (status === 'warning' || status === 'optional') {
        return <IconWarningAmber />
    }
    return <IconErrorOutline />
}

function PreflightItemRow({ name, status, caption }: PreflightItem): JSX.Element {
    const { preflightLoading } = useValues(preflightLogic)
    return (
        <div className={clsx('PreflightItem', preflightLoading ? 'Preflight--loading' : `Preflight--${status}`)}>
            <div className="PreflightItem__icon-container">
                <PreflightCheckIcon status={status} loading={preflightLoading} />
            </div>
            <div className="PreflightItem__text-container">
                <p className="PreflightItem__item-name">{name}</p>
                {caption && (
                    <p data-attr="caption" className="text-muted">
                        {caption}
                    </p>
                )}
            </div>

            <div>
                <p className="Preflight__status-text" data-attr="status-text">
                    {capitalizeFirstLetter(preflightLoading ? 'checking' : status)}
                </p>
            </div>
        </div>
    )
}

export function PreflightCheck(): JSX.Element {
    const { preflight, preflightLoading, preflightMode, checks, areChecksExpanded, checksSummary } =
        useValues(preflightLogic)
    const { setPreflightMode, handlePreflightFinished, setChecksManuallyExpanded, revalidatePreflight } =
        useActions(preflightLogic)

    return (
        <div className="bridge-page Preflight">
            <div>
                <WelcomeLogo view="preflight-check" />
                {!preflightMode ? (
                    <>
                        <div className="Preflight__container-box">
                            <div className="Preflight__header">
                                <p className="Preflight__header--title-text">Select a launch mode</p>
                                <p className="Preflight__header--secondary-text">
                                    What's your plan for this installation? We'll make infrastructure checks
                                    accordingly.
                                </p>
                            </div>
                            <LemonButton
                                fullWidth
                                center
                                type="primary"
                                className="mt-2"
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
                                className="mt-2"
                                size="large"
                                data-attr="preflight-experimentation"
                                onClick={() => setPreflightMode('experimentation')}
                            >
                                Just experimenting
                            </LemonButton>
                            <LemonDivider thick dashed large style={{ marginTop: 24, marginBottom: 24 }} />
                            <p className="text-muted text-center mb-0">
                                We will not enforce some security requirements in experimentation mode.
                            </p>
                        </div>
                        <div style={{ marginTop: 16, textAlign: 'center' }}>
                            <p className="text-muted">
                                {`Have questions? `}
                                <a href="https://posthog.com/support" target="_blank">
                                    Visit support
                                </a>
                            </p>
                        </div>
                    </>
                ) : (
                    <>
                        <div className="Preflight__container-box">
                            <div className="Preflight__header">
                                <p className="Preflight__header--title-text">Validate implementation</p>
                                <p className="Preflight__header--secondary-text">
                                    Validation happens immediately. You can rerun validation checks by clicking
                                    “validate requirements”. If you get stuck, try our{' '}
                                    <a href="https://posthog.com/docs/self-host/deploy/troubleshooting" target="_blank">
                                        troubleshooting guide
                                    </a>{' '}
                                    or our{' '}
                                    <a href="https://posthog.com/docs/self-host/runbook" target="_blank">
                                        self host runbook
                                    </a>
                                    .
                                </p>
                            </div>

                            <div className="Preflight__checks-container">
                                <div className="Preflight__check-summary">
                                    <div
                                        className={clsx(
                                            'Preflight__summary-icon-container',
                                            preflightLoading
                                                ? 'Preflight--loading'
                                                : `Preflight--${checksSummary.summaryStatus}`
                                        )}
                                    >
                                        <PreflightCheckIcon
                                            status={checksSummary.summaryStatus}
                                            loading={preflightLoading}
                                        />
                                    </div>
                                    <div className="Preflight__summary-text-container">
                                        <p className="Preflight__summary-header">Validation checks</p>
                                        <p data-attr="caption" className="text-muted Preflight__summary-description">
                                            {checksSummary.summaryString}
                                        </p>
                                    </div>
                                    <LemonButton
                                        icon={
                                            areChecksExpanded ? (
                                                <IconUnfoldLess style={{ color: 'var(--muted-alt)' }} />
                                            ) : (
                                                <IconUnfoldMore style={{ color: 'var(--muted-alt)' }} />
                                            )
                                        }
                                        onClick={() => {
                                            setChecksManuallyExpanded(!areChecksExpanded)
                                        }}
                                    />
                                </div>
                                <AnimatedCollapsible collapsed={!areChecksExpanded}>
                                    <>
                                        {checks.map((item) => (
                                            <PreflightItemRow key={item.id} {...item} />
                                        ))}
                                    </>
                                </AnimatedCollapsible>
                                <LemonButton
                                    center
                                    fullWidth
                                    size="large"
                                    data-attr="preflight-refresh"
                                    onClick={() => revalidatePreflight()}
                                    disabled={preflightLoading || !preflight}
                                    style={{ borderTopLeftRadius: 0, borderTopRightRadius: 0 }}
                                    icon={<IconRefresh />}
                                >
                                    <span style={{ paddingLeft: 8 }}>Validate requirements</span>
                                </LemonButton>
                            </div>
                            <LemonDivider thick dashed large style={{ marginTop: 24, marginBottom: 24 }} />
                            {checksSummary.summaryStatus !== 'error' ? (
                                <LemonButton
                                    fullWidth
                                    center
                                    type="primary"
                                    className="mt-2"
                                    size="large"
                                    data-attr="preflight-complete"
                                    onClick={handlePreflightFinished}
                                >
                                    Continue
                                </LemonButton>
                            ) : (
                                <LemonRow fullWidth center className="mt-2 Preflight__cannot-continue" size="large">
                                    <p className="text-center text-muted">
                                        All required checks must pass before you can continue
                                    </p>
                                </LemonRow>
                            )}

                            <p className="text-center mt-4 mb-0">
                                Need help? Take a look at our{' '}
                                <a href="https://posthog.com/docs/self-host/deploy/troubleshooting" target="_blank">
                                    documentation
                                </a>{' '}
                                or{' '}
                                <a href="https://posthog.com/support" target="_blank">
                                    visit support
                                </a>
                                .
                            </p>
                        </div>
                    </>
                )}
            </div>
        </div>
    )
}

export default PreflightCheck
