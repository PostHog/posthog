import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function CatalogReviewAccess({ children }: { children: JSX.Element }): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.DataCatalog}
            minAccessLevel={AccessControlLevel.Editor}
        >
            {children}
        </AccessControlAction>
    )
}
