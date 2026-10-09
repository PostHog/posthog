import { useActions, useValues } from 'kea'

import { LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { SceneExport } from 'scenes/sceneTypes'

import { ProductKey } from '~/queries/schema/schema-general'

import { CloudAgentsSceneShell } from '../components/CloudAgentsSceneShell'
import { LoadErrorBanner } from '../components/LoadErrorBanner'
import { PriceEstimator } from '../components/PriceEstimator'
import { RateCard } from '../components/RateCard'
import { TeamLimits } from '../components/TeamLimits'
import { UsageTable } from '../components/UsageTable'
import { UsageTotals } from '../components/UsageTotals'
import { cloudAgentsCatalogLogic } from '../logics/cloudAgentsCatalogLogic'
import { CloudAgentsSceneLogicProps, cloudAgentsSceneLogic } from '../logics/cloudAgentsSceneLogic'
import { cloudAgentsUsageLogic } from '../logics/cloudAgentsUsageLogic'

export const scene: SceneExport<CloudAgentsSceneLogicProps> = {
    component: CloudAgentsUsageScene,
    logic: cloudAgentsSceneLogic,
    paramsToProps: () => ({ scene: 'usage' }),
    productKey: ProductKey.CLOUD_AGENTS,
}

export function CloudAgentsUsageScene(): JSX.Element {
    const { usage, usageLoading, usageLoadFailed, dateFrom, dateTo, groupBy } = useValues(cloudAgentsUsageLogic)
    const { loadUsage, setDateRange, setGroupBy } = useActions(cloudAgentsUsageLogic)
    const { catalog, catalogLoadFailed, catalogLoading } = useValues(cloudAgentsCatalogLogic)
    const { loadCatalog } = useActions(cloudAgentsCatalogLogic)

    return (
        <CloudAgentsSceneShell activeTab="usage">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <DateFilter
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    onChange={setDateRange}
                    size="small"
                    data-attr="cloud-agents-usage-date-range"
                />
                <LemonSegmentedButton
                    size="small"
                    value={groupBy}
                    onChange={setGroupBy}
                    options={[
                        { value: 'day', label: 'By day' },
                        { value: 'preset', label: 'By preset' },
                    ]}
                    data-attr="cloud-agents-usage-group-by"
                />
            </div>
            {usage === null && usageLoadFailed ? (
                <LoadErrorBanner what="the usage" onRetry={loadUsage} retrying={usageLoading} />
            ) : usage === null ? (
                <LemonSkeleton className="h-20" />
            ) : (
                <>
                    <UsageTotals totals={usage.totals} />
                    <UsageTable />
                </>
            )}
            <TeamLimits />
            {catalog === null && catalogLoadFailed ? (
                <LoadErrorBanner what="the prices" onRetry={loadCatalog} retrying={catalogLoading} />
            ) : (
                <div className="grid grid-cols-1 items-start gap-4 @min-[56rem]/main-content:grid-cols-2">
                    <PriceEstimator />
                    <RateCard />
                </div>
            )}
        </CloudAgentsSceneShell>
    )
}
