import { ModelsOverviewTab } from 'products/data_modeling/frontend/ModelsOverviewTab'

import { CatalogToReview } from './CatalogToReview'
import { WarehouseAccessGate } from './WarehouseAccessGate'

export function CatalogOverview(): JSX.Element {
    return (
        <WarehouseAccessGate>
            <div data-quill className="flex flex-col gap-6">
                <ModelsOverviewTab />
                <CatalogToReview />
            </div>
        </WarehouseAccessGate>
    )
}
