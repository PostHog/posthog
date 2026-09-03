import { LinkedHogFunctions, getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

export function BatchExportNotifications({ id }: { id: string }): JSX.Element {
    // The sub-template's own event filter plus a binding to this batch export, so the
    // list shows only notifications scoped to the export whose page we are on.
    const filterGroup: CyclotronJobFiltersType = {
        ...getFiltersFromSubTemplateId('batch-export-run-failed'),
        properties: [
            {
                key: 'batch_export_id',
                type: PropertyFilterType.Event,
                value: id,
                operator: PropertyOperator.Exact,
            },
        ],
    }

    return (
        <div className="deprecated-space-y-2">
            <p className="text-secondary mb-0">Get notified when this batch export fails.</p>
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={['batch-export-run-failed']}
                forceFilterGroups={[filterGroup]}
                emptyText="No notifications configured for this batch export."
                queryParams={{ returnTo: `${urls.batchExport(id)}?tab=notifications` }}
            />
        </div>
    )
}
