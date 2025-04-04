// NOTE: This is only to allow testing the new RBAC system

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { RolesAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/RolesAccessControls'

import { PermissionsGrid } from './PermissionsGrid'

export function RoleBasedAccess(): JSX.Element {
    const newAccessControl = useFeatureFlag('ROLE_BASED_ACCESS_CONTROL')
    return newAccessControl ? <RolesAccessControls /> : <PermissionsGrid />
}
