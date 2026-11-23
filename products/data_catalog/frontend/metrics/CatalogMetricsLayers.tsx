import { useValues } from 'kea'

import { CatalogMetricsLayer } from './CatalogMetricsLayer'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { CatalogMetricsNoMatch } from './CatalogMetricsNoMatch'
import { CatalogMetricsTable } from './CatalogMetricsTable'

export function CatalogMetricsLayers(): JSX.Element {
    const { listPages } = useValues(catalogMetricsLogic)

    if (listPages.all.total === 0) {
        return <CatalogMetricsNoMatch />
    }

    return (
        <>
            {listPages.proposed.total > 0 && (
                <CatalogMetricsLayer
                    title="Waiting for approval"
                    count={listPages.proposed.total}
                    dataAttr="data-catalog-metrics-layer-proposed"
                >
                    <CatalogMetricsTable list="proposed" />
                </CatalogMetricsLayer>
            )}
            {listPages.approved.total > 0 && (
                <CatalogMetricsLayer
                    title="Approved"
                    count={listPages.approved.total}
                    dataAttr="data-catalog-metrics-layer-approved"
                >
                    <CatalogMetricsTable list="approved" />
                </CatalogMetricsLayer>
            )}
        </>
    )
}
