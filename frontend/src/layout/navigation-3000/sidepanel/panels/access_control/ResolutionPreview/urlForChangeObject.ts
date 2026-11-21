import { urls } from 'scenes/urls'

import { objectRuleUrl } from '~/layout/navigation-3000/sidepanel/panels/access_control/ResourceAccessControlsV2/accessDetailLogic'
import { APIScopeObject, AccessControlLevel } from '~/types'

import { ResolutionChange } from './resolutionPreviewLogic'

export function urlForChangeObject(change: ResolutionChange): string | null {
    if (change.object_id === null) {
        return null
    }
    // Same link rules as the object rules table on the access control settings page
    const url = objectRuleUrl({
        resource: change.resource as APIScopeObject,
        resource_id: change.object_id,
        name: change.object_name ?? change.object_id,
        short_id: change.object_short_id,
        access_level: change.proposed.access_level as AccessControlLevel,
    })
    return url ? urls.project(change.project_id, url) : null
}
