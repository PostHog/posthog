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
    // Fallback to true if userAccessLevel is not set
    const hasAccess = userAccessLevel ? requiredLevels.includes(userAccessLevel) : true
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
