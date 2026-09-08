import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesChart } from 'lib/components/AppMetrics/AppMetricsTimeSeriesChart'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    isGranularityAvailable,
    realTimeUsageLogic,
    type RealTimeUsageRow,
    type UsageGranularity,
    type UsageRange,
} from './realTimeUsageLogic'

export const scene: SceneExport = {
    component: RealTimeUsage,
}

const RANGE_OPTIONS: { value: UsageRange; label: string }[] = [
    { value: '1d', label: 'Last 24 hours' },
    { value: '7d', label: 'Last 7 days' },
    { value: '30d', label: 'Last 30 days' },
]

const GRANULARITY_OPTIONS: { value: UsageGranularity; label: string }[] = [
    { value: '5m', label: '5 minutes' },
    { value: 'hour', label: 'Hourly' },
    { value: 'day', label: 'Daily' },
]

export function RealTimeUsage(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    // Kept out of the body below so a team without the flag never mounts the logic, which queries
    // on mount against a table their project cannot resolve.
    if (!featureFlags[FEATURE_FLAGS.BILLING_REAL_TIME_USAGE]) {
        return <NotFound object="page" caption="Real-time usage is not available." />
    }

    return <RealTimeUsageBody />
}

function RealTimeUsageBody(): JSX.Element {
    const {
        breakdownByProject,
        hasMultipleProjects,
        projectOptions,
        selectedProjectIds,
        usageData,
        usageDataError,
        usageDataLoading,
        usageGranularity,
        usageRange,
    } = useValues(realTimeUsageLogic)
    const { loadUsageData, setUsageFilters } = useActions(realTimeUsageLogic)
    const projectCount = selectedProjectIds.length || projectOptions.length

    return (
        <SceneContent>
            <SceneTitleSection
                name="Real-time usage"
                description="Usage reported by product services across all projects in this organization. Charges are not available yet."
                resourceType={{ type: 'billing' }}
            />

            <LemonBanner type="warning" className="mt-4">
                Experimental: This page is under construction. Do not rely on this data yet.
            </LemonBanner>

            <div className="mt-6 max-w-300 space-y-4">
                <div className="flex flex-wrap items-end gap-4">
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Time range</LemonLabel>
                        <LemonSegmentedButton
                            value={usageRange}
                            onChange={(value) =>
                                setUsageFilters({
                                    range: value as UsageRange,
                                    granularity: usageGranularity,
                                    projectIds: selectedProjectIds,
                                    breakdownByProject,
                                })
                            }
                            options={RANGE_OPTIONS}
                            size="small"
                        />
                    </div>
                    <div className="flex flex-col gap-1">
                        <LemonLabel>Granularity</LemonLabel>
                        <LemonSegmentedButton
                            value={usageGranularity}
                            onChange={(value) =>
                                setUsageFilters({
                                    range: usageRange,
                                    granularity: value as UsageGranularity,
                                    projectIds: selectedProjectIds,
                                    breakdownByProject,
                                })
                            }
                            options={GRANULARITY_OPTIONS.map((option) => ({
                                ...option,
                                disabledReason: isGranularityAvailable(option.value, usageRange)
                                    ? undefined
                                    : 'Only available for the last 24 hours',
                            }))}
                            size="small"
                        />
                    </div>
                    {hasMultipleProjects && (
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Projects</LemonLabel>
                            <LemonInputSelect
                                mode="multiple"
                                displayMode="count"
                                bulkActions="select-and-clear-all"
                                className="min-w-50"
                                value={selectedProjectIds.map(String)}
                                onChange={(values) =>
                                    setUsageFilters({
                                        range: usageRange,
                                        granularity: usageGranularity,
                                        projectIds: values.map(Number).filter(Number.isInteger),
                                        breakdownByProject,
                                    })
                                }
                                placeholder="All projects"
                                options={projectOptions}
                                allowCustomValues={false}
                                data-attr="real-time-usage-project-filter"
                            />
                        </div>
                    )}
                    {hasMultipleProjects && (
                        <div className="flex flex-col gap-1">
                            <LemonLabel>Break down by</LemonLabel>
                            <LemonSelect
                                value={breakdownByProject}
                                onChange={(value) =>
                                    setUsageFilters({
                                        range: usageRange,
                                        granularity: usageGranularity,
                                        projectIds: selectedProjectIds,
                                        breakdownByProject: value,
                                    })
                                }
                                options={[
                                    { value: false, label: 'Organization-wide' },
                                    { value: true, label: 'Project' },
                                ]}
                                data-attr="real-time-usage-project-breakdown"
                            />
                        </div>
                    )}
                    <LemonButton
                        className="ml-auto"
                        icon={<IconRefresh />}
                        type="secondary"
                        size="small"
                        loading={usageDataLoading}
                        onClick={loadUsageData}
                        data-attr="real-time-usage-refresh"
                    >
                        Refresh
                    </LemonButton>
                </div>

                {usageDataError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadUsageData }}>
                        Couldn't load usage records. Refresh the page, and if it keeps happening contact support.
                    </LemonBanner>
                ) : !usageDataLoading && usageData?.rows.length === 0 ? (
                    <LemonBanner type="info">No usage records have been received for this period.</LemonBanner>
                ) : (
                    <>
                        <section>
                            <h2 className="mb-1 text-lg font-semibold">Usage over time</h2>
                            <p className="mb-3 text-sm text-secondary">
                                Each line represents one {breakdownByProject ? 'project, ' : ''}product area, usage
                                type, and unit.
                            </p>
                            <div className="relative h-100 rounded border bg-surface-primary p-2">
                                {!usageData ? (
                                    <LemonSkeleton className="size-full" />
                                ) : (
                                    <AppMetricsTimeSeriesChart timeSeries={usageData.timeSeries} showLegend />
                                )}
                                {usageDataLoading && projectCount > 0 && (
                                    <div
                                        className="absolute inset-0 flex items-center justify-center bg-surface-primary/80"
                                        aria-live="polite"
                                    >
                                        <span className="rounded border bg-surface-primary px-3 py-2 text-sm text-secondary shadow-sm">
                                            Loading usage for {projectCount} project{projectCount === 1 ? '' : 's'}…
                                        </span>
                                    </div>
                                )}
                            </div>
                        </section>

                        <section>
                            <h2 className="mb-3 text-lg font-semibold">Usage breakdown</h2>
                            <LemonTable<RealTimeUsageRow>
                                dataSource={usageDataLoading ? [] : (usageData?.rows ?? [])}
                                loading={usageDataLoading || !usageData}
                                loadingSkeletonRows={5}
                                columns={[
                                    ...(breakdownByProject
                                        ? [{ title: 'Project', key: 'projectName', dataIndex: 'projectName' as const }]
                                        : []),
                                    { title: 'Product area', key: 'producerId', dataIndex: 'producerId' },
                                    { title: 'Usage type', key: 'usageKey', dataIndex: 'usageKey' },
                                    { title: 'Unit', key: 'unit', dataIndex: 'unit' },
                                    {
                                        title: 'Quantity',
                                        key: 'quantity',
                                        dataIndex: 'quantity',
                                        align: 'right',
                                        render: (quantity) => humanFriendlyNumber(Number(quantity)),
                                    },
                                ]}
                            />
                        </section>
                    </>
                )}
            </div>
        </SceneContent>
    )
}
