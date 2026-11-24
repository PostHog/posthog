import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { OrganizationPersonalAPIKeysTable } from './OrganizationPersonalAPIKeysTable'
import { OrganizationSecuritySettingGate } from './OrganizationSecuritySettingGate'

export function OrganizationPersonalAPIKeys(): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // PayGateMini falls through to its children when billing carries no metadata for the feature,
    // so the entitlement is checked here too. Otherwise the table below mounts and its first
    // request comes back as a payment prompt.
    const entitled = hasAvailableFeature(AvailableFeature.ORGANIZATION_SECURITY_SETTINGS)

    if (restrictionReason) {
        return todayRailNav ? (
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                {restrictionReason}
            </Text>
        ) : (
            <p className="text-muted">{restrictionReason}</p>
        )
    }

    return (
        <OrganizationSecuritySettingGate featureDetail="organization-personal-api-keys">
            {entitled ? <OrganizationPersonalAPIKeysTable /> : null}
        </OrganizationSecuritySettingGate>
    )
}
