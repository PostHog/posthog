import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { OrganizationBasicType } from '~/types'

export function AccessLevelIndicator({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    return (
        <LemonTag className="AccessLevelIndicator" title={`Your ${organization.name} organization access level`}>
            {(organization.membership_level ? membershipLevelToName.get(organization.membership_level) : null) || '?'}
        </LemonTag>
    )
}
