import { useValues } from 'kea'

import { OrganizationMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { organizationLogic } from 'scenes/organizationLogic'

import { ServiceAccountsTable } from './ServiceAccountsTable'

export function ServiceAccounts(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const enabled = useFeatureFlag('SERVICE_ACCOUNTS')

    if (
        !enabled ||
        !currentOrganization ||
        (currentOrganization.membership_level ?? 0) < OrganizationMembershipLevel.Admin
    ) {
        return null
    }

    return <ServiceAccountsTable organizationId={currentOrganization.id} />
}
