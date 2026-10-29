import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { DataCatalogMetricApi } from '../generated/api.schemas'

/** The measure has the same calculation as a catalog metric, with an extra filter. */
export function ProposedRowDerivedFrom({ metric }: { metric: DataCatalogMetricApi | undefined }): JSX.Element {
    if (!metric) {
        return <span className="text-secondary text-xs">Derived from a catalog metric</span>
    }
    return (
        <span className="text-secondary text-xs">
            Derived from{' '}
            <Link to={urls.dataCatalogMetric(metric.name)} data-attr="data-catalog-usage-derived-from-link">
                {metric.display_name || metric.name}
            </Link>
        </span>
    )
}
