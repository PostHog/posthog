import './PreflightCheck.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCollapse, IconExpand, IconWarning } from '@posthog/icons'
import { Link, Spinner } from '@posthog/lemon-ui'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonRow } from 'lib/lemon-ui/LemonRow'
import { IconErrorOutline, IconRefresh } from 'lib/lemon-ui/icons'
import { capitalizeFirstLetter } from 'lib/utils'
import { SceneExport } from 'scenes/sceneTypes'

import { PreflightCheckStatus, PreflightItem, preflightLogic } from './preflightLogic'

export const scene: SceneExport = {
    component: PreflightCheck,
    logic: preflightLogic,
}

function PreflightCheckIcon({ status, loading }: { status: PreflightCheckStatus; loading?: boolean }): JSX.Element {
    if (loading) {
        return <Spinner textColored className="text-accent" />
    }
    if (status === 'validated') {
        return <IconCheckCircle />
    } else if (status === 'warning' || status === 'optional') {
        return <IconWarning />
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
                    <p data-attr="caption" className="text-secondary">
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
        <BridgePage
            view="preflight-check"
            footer={
                <p className="text-center mt-4 mb-0">
                    Need help? Take a look at our{' '}
                    <Link
                        to="https://posthog.com/docs/self-host/deploy/troubleshooting"
                        target="_blank"
                        targetBlankIcon={false}
                    >
                        documentation
                    </Link>{' '}
                    or{' '}
                    <Link to="https://posthog.com/support" target="_blank" targetBlankIcon={false}>
                        visit community support
                    </Link>
                    .
                </p>
            }
            fixedWidth={false}
        >
            <div className="Preflight">
                {!preflightMode ? (
                    <>
                        <div className="Preflight__header">
                            <p className="Preflight__header--title-text">Select a launch mode</p>
                            <p className="Preflight__header--secondary-text">
                                What's your plan for this installation? We'll make infrastructure checks accordingly.
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
                        <LemonDivider thick dashed className="my-6" />
                        <p className="text-secondary text-center mb-0">
                            We will not enforce some security requirements in experimentation mode.
                        </p>
                    </>
                ) : (
                    <>
                        <div className="Preflight__header">
                            <p className="Preflight__header--title-text">Validate implementation</p>
                            <p className="Preflight__header--secondary-text">
                                Validation happens immediately. You can rerun validation checks by clicking “validate
                                requirements”. If you get stuck, try our{' '}
                                <Link to="https://posthog.com/docs/self-host/deploy/troubleshooting" target="_blank">
                                    troubleshooting guide
                                </Link>{' '}
                                or our{' '}
                                <Link to="https://posthog.com/docs/runbook" target="_blank">
                                    self-host runbook
                                </Link>
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
                                    <p data-attr="caption" className="text-secondary Preflight__summary-description">
                                        {checksSummary.summaryString}
                                    </p>
                                </div>
                                <LemonButton
                                    icon={
                                        areChecksExpanded ? (
                                            <IconCollapse style={{ color: 'var(--color-text-secondary)' }} />
                                        ) : (
                                            <IconExpand style={{ color: 'var(--color-text-secondary)' }} />
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
                                icon={<IconRefresh />}
                            >
                                Validate requirements
                            </LemonButton>
                        </div>
                        <LemonDivider thick dashed className="my-6" />
                        {checksSummary.summaryStatus !== 'error' || preflightMode == 'experimentation' ? (
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
                                <p className="text-center text-secondary">
                                    All required checks must pass before you can continue
                                </p>
                            </LemonRow>
                        )}
                    </>
                )}
            </div>
        </BridgePage>
    )
}

export default PreflightCheck
