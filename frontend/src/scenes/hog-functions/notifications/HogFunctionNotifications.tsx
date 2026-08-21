import { humanizeHogFunctionType } from 'scenes/hog-functions/hog-function-utils'
import { LinkedHogFunctions, getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { urls } from 'scenes/urls'

import { CyclotronJobFiltersType, HogFunctionTypeType, PropertyFilterType, PropertyOperator } from '~/types'

export function HogFunctionNotifications({ id, type }: { id: string; type: HogFunctionTypeType }): JSX.Element {
    const humanizedType = humanizeHogFunctionType(type)

    // The sub-template's own event filter plus a binding to this function, so the
    // list shows only notifications scoped to the function whose page we are on.
    const filterGroup: CyclotronJobFiltersType = {
        ...getFiltersFromSubTemplateId('hog-function-state-changed'),
        properties: [
            {
                key: 'hog_function_id',
                type: PropertyFilterType.Event,
                value: id,
                operator: PropertyOperator.Exact,
            },
        ],
    }

    return (
        <div className="deprecated-space-y-2">
            <p className="text-secondary mb-0">
                Get notified when PostHog disables or slows down this {humanizedType} because it keeps failing.
            </p>
            <LinkedHogFunctions
                type="internal_destination"
                subTemplateIds={['hog-function-state-changed']}
                forceFilterGroups={[filterGroup]}
                emptyText={`No notifications configured for this ${humanizedType}.`}
                queryParams={{ returnTo: urls.hogFunction(id, 'notifications') }}
            />
        </div>
    )
}
