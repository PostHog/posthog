type AccessControlLevelNone = 'none'
type AccessControlLevelMember = AccessControlLevelNone | 'member' | 'admin'
type AccessControlLevelResource = AccessControlLevelNone | 'viewer' | 'editor'
type AccessControlLevel = AccessControlLevelMember | AccessControlLevelResource

interface AccessControlActionProps {
    children: (props: { disabled: boolean; disabledReason: string | null }) => React.ReactElement
    userAccessLevel?: AccessControlLevel
    minAccessLevel: AccessControlLevel
    resourceType: string
}

const orderedAccessLevels = (resourceType: string): AccessControlLevel[] => {
    if (resourceType === 'project' || resourceType === 'organization') {
        return ['none', 'member', 'admin']
    }
    return ['none', 'viewer', 'editor']
}

export const accessLevelSatisfied = (
    resourceType: string,
    currentLevel: AccessControlLevel,
    requiredLevel: AccessControlLevel
): boolean => {
    const levels = orderedAccessLevels(resourceType)
    return levels.indexOf(currentLevel) >= levels.indexOf(requiredLevel)
}

// This is a wrapper around a component that checks if the user has access to the resource
// and if not, it disables the component and shows a reason why
export const AccessControlAction = ({
    children,
    userAccessLevel,
    minAccessLevel,
    resourceType = 'resource',
}: AccessControlActionProps): JSX.Element => {
    const hasAccess = userAccessLevel ? accessLevelSatisfied(resourceType, userAccessLevel, minAccessLevel) : false
    const disabledReason = !hasAccess
        ? `You don't have sufficient permissions for this ${resourceType}. Your access level (${userAccessLevel}) doesn't meet the required level (${minAccessLevel}).`
        : null

    return children({
        disabled: !hasAccess,
        disabledReason,
    })
}
