import { DatabaseTablePreview } from 'lib/components/TablePreview/DatabaseTablePreview'
import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

export function FunnelDataWarehouseStepDefinitionPopover({
    item,
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return defaultView
    }

    return <FunnelDataWarehouseStepDefinitionPopoverContent table={item as DataWarehouseTableForInsight} />
}

function FunnelDataWarehouseStepDefinitionPopoverContent({
    table,
}: {
    table: DataWarehouseTableForInsight
}): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <DatabaseTablePreview table={table} emptyMessage="No table selected" limit={5} />
        </div>
    )
}
