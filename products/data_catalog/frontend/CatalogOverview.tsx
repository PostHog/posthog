import { ModelsOverviewTab } from 'products/data_modeling/frontend/ModelsOverviewTab'

import { CatalogToReview } from './CatalogToReview'
import { WarehouseAccessGate } from './WarehouseAccessGate'

export function CatalogOverview(): JSX.Element {
    return (
        <div data-quill className="flex flex-col gap-6">
            <WarehouseAccessGate>
                <ModelsOverviewTab />
            </WarehouseAccessGate>
            <CatalogToReview />
        </div>
    )
}
