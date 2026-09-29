import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { WarehouseSyncWarningList } from '~/queries/nodes/DataNode/WarehouseSyncWarningList'
import { warehouseSyncWarnings } from '~/queries/nodes/DataNode/warehouseSyncWarnings'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { InsightLogicProps } from '~/types'

export function InsightWarehouseSyncBanner({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { response } = useValues(dataNodeLogic({ key: insightVizDataNodeKey(insightProps) } as DataNodeLogicProps))
    const syncWarnings = warehouseSyncWarnings(response && 'warnings' in response ? response.warnings : null)
    if (syncWarnings.length === 0) {
        return null
    }

    return (
        <LemonBanner type="warning" data-attr="insight-warehouse-sync-warnings">
            Some warehouse tables this insight reads are out of date, so its results may not be current:
            <WarehouseSyncWarningList warnings={syncWarnings} />
        </LemonBanner>
    )
}
