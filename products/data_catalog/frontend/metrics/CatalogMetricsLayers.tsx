import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { CatalogMetricsLayer } from './CatalogMetricsLayer'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { CatalogMetricsNoMatch } from './CatalogMetricsNoMatch'
import { CatalogMetricsTable } from './CatalogMetricsTable'

/** The catalog metrics as two short lists: the metrics that wait for approval, then the approved metrics. */
export function CatalogMetricsLayers(): JSX.Element {
    const { listPages } = useValues(catalogMetricsLogic)

    if (listPages.all.total === 0) {
        return <CatalogMetricsNoMatch />
    }

    return (
        <>
            {listPages.proposed.total > 0 && (
                <CatalogMetricsLayer
                    title="Proposed"
                    count={listPages.proposed.total}
                    description={
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Waiting for approval.
                        </Text>
                    }
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
