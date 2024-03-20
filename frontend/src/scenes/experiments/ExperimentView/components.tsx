import '../Experiment.scss'

import { IconWarning } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { PageHeader } from 'lib/components/PageHeader'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { useEffect, useState } from 'react'
import { urls } from 'scenes/urls'

import { ProgressStatus } from '~/types'

import { ResetButton } from '../Experiment'
import { experimentLogic } from '../experimentLogic'
import { getExperimentStatus } from '../experimentsLogic'

export function ExperimentBanner(): JSX.Element {
    const { experiment, isExperimentRunning, isExperimentStopped } = useValues(experimentLogic)

    const { resetRunningExperiment, archiveExperiment, endExperiment, launchExperiment, setEditExperiment } =
        useActions(experimentLogic)

    if (isExperimentStopped) {
        return (
            <LemonBanner type="info">
                <div className="flex">
                    <div className="w-1/2 flex items-center">
                        This experiment has been <b>&nbsp;stopped.</b>
                    </div>

                    <div className="w-1/2 flex flex-col justify-end">
                        <div className="ml-auto inline-flex space-x-2">
                            <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                            <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                                <b>Archive</b>
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </LemonBanner>
        )
    }

    if (isExperimentRunning) {
        return (
            <LemonBanner type="info">
                <div className="flex">
                    <div className="w-1/2 flex items-center">
                        This experiment is <b>&nbsp;active.</b>
                    </div>

                    <div className="w-1/2 flex flex-col justify-end">
                        <div className="ml-auto inline-flex space-x-2">
                            <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                            <LemonButton type="secondary" status="danger" onClick={() => endExperiment()}>
                                Stop
                            </LemonButton>
                        </div>
                    </div>
                </div>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner type="info">
            <div className="flex">
                <div className="w-1/2 flex items-center">
                    This experiment is <b>&nbsp;draft.</b>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto inline-flex space-x-2">
                        <LemonButton type="secondary" onClick={() => setEditExperiment(true)}>
                            Edit
                        </LemonButton>
                        <LemonButton type="primary" onClick={() => launchExperiment()}>
                            Launch
                        </LemonButton>
                    </div>
                </div>
            </div>
        </LemonBanner>
    )
}

export function ExperimentLoader(): JSX.Element {
    return (
        <LemonTable
            dataSource={[]}
            columns={[
                {
                    title: '',
                    dataIndex: '',
                },
            ]}
            loadingSkeletonRows={8}
            loading={true}
        />
    )
}

export function ExperimentLoadingAnimation(): JSX.Element {
    function EllipsisAnimation(): JSX.Element {
        const [ellipsis, setEllipsis] = useState('.')

        useEffect(() => {
            let count = 1
            let direction = 1

            const interval = setInterval(() => {
                setEllipsis('.'.repeat(count))
                count += direction

                if (count === 3 || count === 1) {
                    direction *= -1
                }
            }, 300)

            return () => clearInterval(interval)
        }, [])

        return <span>{ellipsis}</span>
    }

    return (
        <div className="flex flex-col flex-1 justify-center items-center">
            <Animation type={AnimationType.LaptopHog} />
            <div className="text-xs text-muted w-44">
                <span className="mr-1">Fetching experiment results</span>
                <EllipsisAnimation />
            </div>
        </div>
    )
}

export function FeatureFlagInfo(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    if (!experiment.feature_flag) {
        return <></>
    }

    return (
        <div className="block">
            <h2 className="font-semibold text-lg mb-1">Feature flag</h2>
            <div className="inline-flex items-center space-x-2">
                {getExperimentStatus(experiment) === ProgressStatus.Running && !experiment.feature_flag?.active && (
                    <Tooltip
                        placement="bottom"
                        title="Your experiment is running, but the linked flag is disabled. No data is being collected."
                    >
                        <IconWarning
                            style={{ transform: 'translateY(2px)' }}
                            className="mr-1 text-danger"
                            fontSize="18px"
                        />
                    </Tooltip>
                )}
                <CopyToClipboardInline
                    iconStyle={{ color: 'var(--lemon-button-icon-opacity)' }}
                    className="font-normal text-sm"
                    description="feature flag key"
                >
                    {experiment.feature_flag.key}
                </CopyToClipboardInline>
                <LemonDivider className="my-0" vertical />
                <Link
                    target="_blank"
                    className="font-semibold"
                    to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                >
                    Manage
                </Link>
            </div>
        </div>
    )
}

export function PageHeaderCustom(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)
    const { launchExperiment, setEditExperiment, loadExperimentResults, loadSecondaryMetricResults } =
        useActions(experimentLogic)

    return (
        <PageHeader
            buttons={
                <>
                    <div className="flex flex-row gap-2">
                        <>
                            <More
                                overlay={
                                    <>
                                        {experiment && !isExperimentRunning && (
                                            <>
                                                <LemonButton fullWidth onClick={() => setEditExperiment(true)}>
                                                    Edit
                                                </LemonButton>
                                                <LemonButton fullWidth onClick={() => launchExperiment()}>
                                                    Launch
                                                </LemonButton>
                                            </>
                                        )}
                                        {experiment && isExperimentRunning && (
                                            <>
                                                <LemonButton
                                                    onClick={() => loadExperimentResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-experiment"
                                                >
                                                    Refresh experiment results
                                                </LemonButton>
                                                <LemonButton
                                                    onClick={() => loadSecondaryMetricResults(true)}
                                                    fullWidth
                                                    data-attr="refresh-secondary-metrics"
                                                >
                                                    Refresh secondary metrics
                                                </LemonButton>
                                            </>
                                        )}
                                    </>
                                }
                            />
                        </>
                    </div>
                </>
            }
        />
    )
}
