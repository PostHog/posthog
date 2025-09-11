import { AccessControlResourceType } from '~/types'

type AccessControlLevelNone = 'none'
type AccessControlLevelMember = AccessControlLevelNone | 'member' | 'admin'
type AccessControlLevelResource = AccessControlLevelNone | 'viewer' | 'editor' | 'manager'
type AccessControlLevel = AccessControlLevelMember | AccessControlLevelResource

interface AccessControlActionProps {
    children: (props: { disabled: boolean; disabledReason: string | null }) => React.ReactElement
    userAccessLevel?: AccessControlLevel
    minAccessLevel: AccessControlLevel
    resourceType: AccessControlResourceType
}

const orderedAccessLevels = (resourceType: AccessControlResourceType): AccessControlLevel[] => {
    if (resourceType === AccessControlResourceType.Project || resourceType === AccessControlResourceType.Organization) {
        return ['none', 'member', 'admin']
    }
    return ['none', 'viewer', 'editor', 'manager']
}

export const resourceTypeToString = (resourceType: AccessControlResourceType): string => {
    if (resourceType === AccessControlResourceType.FeatureFlag) {
        return 'feature flag'
    } else if (resourceType === AccessControlResourceType.SessionRecording) {
        return 'session recording'
    }

    // The rest are single words
    return resourceType
}

export const accessLevelSatisfied = (
    resourceType: AccessControlResourceType,
    currentLevel: AccessControlLevel,
    requiredLevel: AccessControlLevel
): boolean => {
    const levels = orderedAccessLevels(resourceType)
    return levels.indexOf(currentLevel) >= levels.indexOf(requiredLevel)
}

export const getAccessControlDisabledReason = (
    resourceType: AccessControlResourceType,
    userAccessLevel: AccessControlLevel | undefined,
    minAccessLevel: AccessControlLevel
): string | null => {
    const hasAccess = userAccessLevel ? accessLevelSatisfied(resourceType, userAccessLevel, minAccessLevel) : true
    if (!hasAccess) {
        return `You don't have sufficient permissions for this ${resourceTypeToString(
            resourceType
        )}. Your access level (${userAccessLevel}) doesn't meet the required level (${minAccessLevel}).`
    }
    return null
}

// This is a wrapper around a component that checks if the user has access to the resource
// and if not, it disables the component and shows a reason why
export const AccessControlAction = ({
    children,
    userAccessLevel,
    minAccessLevel,
    resourceType = AccessControlResourceType.Project,
}: AccessControlActionProps): JSX.Element => {
    const disabledReason = getAccessControlDisabledReason(resourceType, userAccessLevel, minAccessLevel)

    return children({
        disabled: !!disabledReason,
        disabledReason,
    })
}
