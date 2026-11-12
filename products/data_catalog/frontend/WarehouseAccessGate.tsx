import { AccessDenied } from 'lib/components/AccessDenied'
import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

export function WarehouseAccessGate({ children }: { children: JSX.Element }): JSX.Element {
    if (!userHasAccess(AccessControlResourceType.WarehouseObjects, AccessControlLevel.Viewer)) {
        return (
            <AccessDenied
                reason="You don't have access to Data warehouse tables & views, so this section isn't available."
                inline
            />
        )
    }
    return children
}
