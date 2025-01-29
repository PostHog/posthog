// NOTE: This is only to allow testing the new RBAC system

import { LemonBanner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { RolesAndResourceAccessControls } from '~/layout/navigation-3000/sidepanel/panels/access_control/RolesAndResourceAccessControls'

import { PermissionsGrid } from './PermissionsGrid'

export function RoleBasedAccess(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateAccessControlVersion } = useActions(teamLogic)
    const newAccessControl = useFeatureFlag('ROLE_BASED_ACCESS_CONTROL')

    if (newAccessControl && currentTeam?.access_control_version === 'v2') {
        return <RolesAndResourceAccessControls noAccessControls />
    }

    return (
        <>
            {newAccessControl && (
                <LemonBanner
                    className="mb-4"
                    type="warning"
                    action={{
                        children: 'Upgrade now',
                        onClick: () => updateAccessControlVersion(),
                    }}
                >
                    You're eligible to upgrade to our new access control system. This will allow you to better manage
                    your roles across more resources on PostHog.
                </LemonBanner>
            )}
            <PermissionsGrid />
        </>
    )
}
