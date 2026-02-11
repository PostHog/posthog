import { DefinitionPopoverRendererProps, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

export function DataWarehouseFunnelStepDefinitionPopover({
    group,
    defaultView,
}: DefinitionPopoverRendererProps): JSX.Element | null {
    if (group.type !== TaxonomicFilterGroupType.DataWarehouse) {
        return null
    }

    return (
        <div className="space-y-2">
            <div className="min-h-10 rounded border border-dashed border-border" />
            {/* {defaultView} */}
        </div>
    )
}
