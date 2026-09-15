import { LinkedHogFunctions, getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

export interface NotificationsTabProps {
    id: string
}

export function NotificationsTab({ id }: NotificationsTabProps): JSX.Element {
    const filterGroup: CyclotronJobFiltersType = {
        ...getFiltersFromSubTemplateId('warehouse-source-sync-failed'),
        properties: [
            {
                key: 'source_id',
                type: PropertyFilterType.Event,
                value: id,
                operator: PropertyOperator.Exact,
            },
        ],
    }

    return (
        <div className="flex flex-col gap-2">
            <p className="text-secondary mb-0">Get notified when a table on this source fails to sync.</p>
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={['warehouse-source-sync-failed']}
                forceFilterGroups={[filterGroup]}
                emptyText="No notifications set up for this source."
                queryParams={{ returnTo: urls.dataWarehouseSource(`managed-${id}`, 'notifications') }}
            />
        </div>
    )
}
