import { useValues } from 'kea'

import { accessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/accessControlLogic'

import { WithAccessControl } from '../../types'

interface AccessControlActionProps {
    children: (props: { disabled: boolean; disabledReason: string | null }) => React.ReactElement
    userAccessLevel?: WithAccessControl['user_access_level']
    requiredLevels: WithAccessControl['user_access_level'][]
    resourceType?: string
}

export const AccessControlAction = ({
    children,
    userAccessLevel,
    requiredLevels,
    resourceType = 'resource',
}: AccessControlActionProps): JSX.Element => {
    const { hasResourceAccess } = useValues(accessControlLogic)

    const hasAccess = hasResourceAccess({ userAccessLevel, requiredLevels })
    const disabledReason = !hasAccess
        ? `You don't have sufficient permissions for this ${resourceType}. Your access level (${userAccessLevel}) doesn't meet the required level (${requiredLevels.join(
              ' or '
          )}).`
        : null

    return children({
        disabled: !hasAccess,
        disabledReason,
    })
}
