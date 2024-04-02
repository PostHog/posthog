import '../Experiment.scss'

import { LemonButton, LemonDivider, LemonTable, LemonTag, LemonTagType } from '@posthog/lemon-ui'
import { Empty } from 'antd'
import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'
import { PageHeader } from 'lib/components/PageHeader'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { capitalizeFirstLetter } from 'lib/utils'
import { useEffect, useState } from 'react'

import { filtersToQueryNode } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ExperimentResults, InsightShortId } from '~/types'

import { ResetButton } from '../Experiment'
import { experimentLogic } from '../experimentLogic'
import { getExperimentInsightColour, transformResultFilters } from '../utils'

export function VariantTag({ variantKey }: { variantKey: string }): JSX.Element {
    const { experimentResults, getIndexForVariant } = useValues(experimentLogic)

    return (
        <span className="flex items-center space-x-1">
            <div
                className="w-2 h-2 rounded-full mr-0.5"
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    backgroundColor: getExperimentInsightColour(getIndexForVariant(experimentResults, variantKey)),
                }}
            />
            <span className="font-semibold">{capitalizeFirstLetter(variantKey)}</span>
        </span>
    )
}

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

export function ResultsQuery({
    targetResults,
    showTable,
}: {
    targetResults: ExperimentResults['result'] | null
    showTable: boolean
}): JSX.Element {
    return (
        <Query
            query={{
                kind: NodeKind.InsightVizNode,
                source: filtersToQueryNode(transformResultFilters(targetResults?.filters ?? {})),
                showTable,
                showLastComputation: true,
                showLastComputationRefresh: false,
            }}
            context={{
                insightProps: {
                    dashboardItemId: targetResults?.fakeInsightId as InsightShortId,
                    cachedInsight: {
                        short_id: targetResults?.fakeInsightId as InsightShortId,
                        filters: transformResultFilters(targetResults?.filters ?? {}),
                        result: targetResults?.insight,
                        disable_baseline: true,
                        last_refresh: targetResults?.last_refresh,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}

export function NoResultsEmptyState(): JSX.Element {
    const { experimentResultsLoading, experimentResultCalculationError } = useValues(experimentLogic)

    if (experimentResultsLoading) {
        return <></>
    }

    return (
        <div>
            <h2 className="font-semibold text-lg">Results</h2>
            <div className="border rounded bg-bg-light pt-6 pb-8 text-muted">
                <div className="flex flex-col items-center mx-auto">
                    <Empty className="my-4" image={Empty.PRESENTED_IMAGE_SIMPLE} description="" />
                    <h2 className="text-xl font-semibold leading-tight">There are no experiment results yet</h2>
                    {!!experimentResultCalculationError && (
                        <div className="text-sm text-center text-balance">{experimentResultCalculationError}</div>
                    )}
                    <div className="text-sm text-center text-balance">
                        Wait a bit longer for your users to be exposed to the experiment. Double check your feature flag
                        implementation if you're still not seeing results.
                    </div>
                </div>
            </div>
        </div>
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
