import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

export function DataCatalogPrimaryAction(): JSX.Element {
    return (
        <LemonButton type="primary" to={urls.dataCatalogNewMetric()} data-attr="data-catalog-new-metric-button">
            Define your first metric
        </LemonButton>
    )
}
