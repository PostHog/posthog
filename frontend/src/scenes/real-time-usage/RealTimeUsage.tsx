import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSegmentedButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { AppMetricsTimeSeriesChart } from 'lib/components/AppMetrics/AppMetricsTimeSeriesChart'
import { LemonTable } from 'lib/lemon-ui/LemonTable'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { realTimeUsageLogic, type RealTimeUsageRow, type UsageGranularity, type UsageRange } from './realTimeUsageLogic'

export const scene: SceneExport = {
    component: RealTimeUsage,
}

const RANGE_OPTIONS: { value: UsageRange; label: string }[] = [
    { value: '1d', label: 'Last 24 hours' },
    { value: '7d', label: 'Last 7 days' },
    { value: '30d', label: 'Last 30 days' },
]

const GRANULARITY_OPTIONS: { value: UsageGranularity; label: string }[] = [
    { value: 'hour', label: 'Hourly' },
    { value: 'day', label: 'Daily' },
]

export function RealTimeUsage(): JSX.Element {
    const { usageData, usageDataError, usageDataLoading, usageGranularity, usageRange } = useValues(realTimeUsageLogic)
    const { loadUsageData, setUsageGranularity, setUsageRange } = useActions(realTimeUsageLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Real-time usage"
                description="Usage reported by product services across all projects in this organization. Charges are not available yet."
                resourceType={{ type: 'billing' }}
                actions={
                    <LemonButton
                        icon={<IconRefresh />}
                        type="secondary"
                        size="small"
                        loading={usageDataLoading}
                        onClick={loadUsageData}
                        data-attr="real-time-usage-refresh"
                    >
                        Refresh
                    </LemonButton>
                }
            />

            <div className="mt-6 max-w-300 space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                    <LemonSegmentedButton
                        value={usageRange}
                        onChange={(value) => setUsageRange(value as UsageRange)}
                        options={RANGE_OPTIONS}
                        size="small"
                    />
                    <LemonSegmentedButton
                        value={usageGranularity}
                        onChange={(value) => setUsageGranularity(value as UsageGranularity)}
                        options={GRANULARITY_OPTIONS}
                        size="small"
                    />
                </div>

                {usageDataError ? (
                    <LemonBanner type="error" action={{ children: 'Try again', onClick: loadUsageData }}>
                        Couldn't load usage records. Refresh the page, and if it keeps happening contact support.
                    </LemonBanner>
                ) : usageDataLoading || !usageData ? (
                    <div className="relative h-100 rounded border bg-surface-primary">
                        <SpinnerOverlay />
                    </div>
                ) : usageData.rows.length === 0 ? (
                    <LemonBanner type="info">No usage records have been received for this period.</LemonBanner>
                ) : (
                    <>
                        <section>
                            <h2 className="mb-1 text-lg font-semibold">Usage over time</h2>
                            <p className="mb-3 text-sm text-secondary">
                                Each line represents one product area, usage type, and unit.
                            </p>
                            <div className="h-100 rounded border bg-surface-primary p-2">
                                <AppMetricsTimeSeriesChart timeSeries={usageData.timeSeries} showLegend />
                            </div>
                        </section>

                        <section>
                            <h2 className="mb-3 text-lg font-semibold">Usage breakdown</h2>
                            <LemonTable<RealTimeUsageRow>
                                dataSource={usageData.rows}
                                columns={[
                                    { title: 'Product area', key: 'producerId', dataIndex: 'producerId' },
                                    { title: 'Usage type', key: 'usageKey', dataIndex: 'usageKey' },
                                    {
                                        title: 'Quantity',
                                        key: 'quantity',
                                        dataIndex: 'quantity',
                                        align: 'right',
                                        render: (quantity) => humanFriendlyNumber(Number(quantity)),
                                    },
                                    { title: 'Unit', key: 'unit', dataIndex: 'unit' },
                                ]}
                            />
                        </section>
                    </>
                )}
            </div>
        </SceneContent>
    )
}
