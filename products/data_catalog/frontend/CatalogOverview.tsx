import { ModelsOverviewStatus } from 'products/data_modeling/frontend/ModelsOverviewStatus'

import { CatalogToReview } from './CatalogToReview'
import { WarehouseAccessGate } from './WarehouseAccessGate'

export function CatalogOverview(): JSX.Element {
    return (
        <WarehouseAccessGate>
            <div data-quill className="flex flex-col gap-6">
                <ModelsOverviewStatus />
                <CatalogToReview />
            </div>
        </WarehouseAccessGate>
    )
}
