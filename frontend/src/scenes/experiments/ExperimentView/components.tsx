import '../Experiment.scss'

import { LemonButton, LemonDivider, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { useEffect, useState } from 'react'

import { ResetButton } from '../Experiment'
import { experimentLogic } from '../experimentLogic'

export function ResultsTag(): JSX.Element {
    const { areResultsSignificant } = useValues(experimentLogic)
    const result: { color: LemonTagType; label: string } = areResultsSignificant
        ? { color: 'success', label: 'Significant' }
        : { color: 'primary', label: 'Not significant' }

    return (
        <LemonTag type={result.color}>
            <b className="uppercase">{result.label}</b>
        </LemonTag>
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

export function PageHeaderCustom(): JSX.Element {
    const { experiment, isExperimentRunning } = useValues(experimentLogic)
    const {
        launchExperiment,
        resetRunningExperiment,
        endExperiment,
        archiveExperiment,
        setEditExperiment,
        loadExperimentResults,
        loadSecondaryMetricResults,
    } = useActions(experimentLogic)

    return (
        <PageHeader
            buttons={
                <>
                    {experiment && !isExperimentRunning && (
                        <div className="flex items-center">
                            <LemonButton type="secondary" className="mr-2" onClick={() => setEditExperiment(true)}>
                                Edit
                            </LemonButton>
                            <LemonButton type="primary" onClick={() => launchExperiment()}>
                                Launch
                            </LemonButton>
                        </div>
                    )}
                    {experiment && isExperimentRunning && (
                        <div className="flex flex-row gap-2">
                            <>
                                <More
                                    overlay={
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
                                    }
                                />
                                <LemonDivider vertical />
                            </>
                            <ResetButton experiment={experiment} onConfirm={resetRunningExperiment} />
                            {!experiment.end_date && (
                                <LemonButton type="secondary" status="danger" onClick={() => endExperiment()}>
                                    Stop
                                </LemonButton>
                            )}
                            {experiment?.end_date &&
                                dayjs().isSameOrAfter(dayjs(experiment.end_date), 'day') &&
                                !experiment.archived && (
                                    <LemonButton type="secondary" status="danger" onClick={() => archiveExperiment()}>
                                        <b>Archive</b>
                                    </LemonButton>
                                )}
                        </div>
                    )}
                </>
            }
        />
    )
}
