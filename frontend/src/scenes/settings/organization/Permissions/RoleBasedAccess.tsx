// NOTE: This is only to allow testing the new RBAC system

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RolesAndResourceAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/RolesAndResourceAccessControls'

import { PermissionsGrid } from './PermissionsGrid'

export function RoleBasedAccess(): JSX.Element {
    const newAccessControl = useFeatureFlag('ROLE_BASED_ACCESS_CONTROL')
    return newAccessControl ? <RolesAndResourceAccessControls noAccessControls /> : <PermissionsGrid />
}
