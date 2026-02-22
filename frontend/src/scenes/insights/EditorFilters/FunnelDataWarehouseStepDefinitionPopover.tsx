import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function FunnelDataWarehouseStepDefinitionPopover({
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return defaultView
    }

    return <div>DataWarehouseFunnelStepDefinitionPopover</div>
}
