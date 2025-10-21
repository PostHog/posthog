import { getAppContext } from 'lib/utils/getAppContext'

import { APIScopeObject, AccessControlLevel, AccessControlResourceType } from '~/types'

/**
 * Returns the minimum allowed access level for a resource.
 * Matches the backend minimum_access_level function in user_access_control.py
 *
 * @param resource - The API scope object to check minimum access for
 * @returns The minimum access level required, or null if no minimum is set
 */
export const getMinimumAccessLevel = (resource: APIScopeObject): AccessControlLevel | null => {
    if (resource === 'action') {
        return AccessControlLevel.Viewer
    }
    return null
}

/**
 * Converts a resource name to its plural form for display purposes.
 * Handles special cases for specific resources that have custom plural forms.
 *
 * @param resource - The API scope object to pluralize
 * @returns The pluralized resource name for display
 */
export const pluralizeResource = (resource: APIScopeObject): string => {
    if (resource === AccessControlResourceType.RevenueAnalytics) {
        return 'revenue analytics'
    } else if (resource === AccessControlResourceType.WebAnalytics) {
        return 'web analytics'
    }

    return resource.replace(/_/g, ' ') + 's'
}

/**
 * Returns the ordered list of access levels available for a given resource type.
 * Different resource types have different sets of available access levels.
 *
 * @param resourceType - The type of resource to get access levels for
 * @returns Array of access levels ordered from lowest to highest
 */
export const orderedAccessLevels = (resourceType: AccessControlResourceType): AccessControlLevel[] => {
    if (resourceType === AccessControlResourceType.Project || resourceType === AccessControlResourceType.Organization) {
        return [AccessControlLevel.None, AccessControlLevel.Member, AccessControlLevel.Admin]
    }
    return [AccessControlLevel.None, AccessControlLevel.Viewer, AccessControlLevel.Editor, AccessControlLevel.Manager]
}

/**
 * Converts a resource type enum to a human-readable string.
 * Handles special cases for specific resource types that have custom display names.
 *
 * @param resourceType - The access control resource type to convert
 * @returns Human-readable string representation of the resource type
 */
export const resourceTypeToString = (resourceType: AccessControlResourceType): string => {
    if (resourceType === AccessControlResourceType.RevenueAnalytics) {
        return 'revenue analytics resource'
    } else if (resourceType === AccessControlResourceType.WebAnalytics) {
        return 'web analytics resource'
    }

    return resourceType.replace(/_/g, ' ')
}

/**
 * Checks if a user's current access level satisfies the required access level for a resource.
 * Uses the ordered access levels to determine if the current level is sufficient.
 *
 * @param resourceType - The type of resource being accessed
 * @param currentLevel - The user's current access level
 * @param requiredLevel - The minimum required access level
 * @returns True if the current level meets or exceeds the required level
 */
export const accessLevelSatisfied = (
    resourceType: AccessControlResourceType,
    currentLevel: AccessControlLevel,
    requiredLevel: AccessControlLevel
): boolean => {
    const levels = orderedAccessLevels(resourceType)
    return levels.indexOf(currentLevel) >= levels.indexOf(requiredLevel)
}

/**
 * Determines why access control is disabled for a user and resource.
 * Checks if the user has sufficient permissions and returns a descriptive reason if not.
 * Falls back to app context if user access level is not provided.
 *
 * @param resourceType - The type of resource being accessed
 * @param minAccessLevel - The minimum required access level
 * @param userAccessLevel - Optional user's current access level (falls back to app context)
 * @param includeAccessDetails - Whether to include specific access level details in the reason
 * @returns Descriptive reason for access denial, or null if access is granted
 */
export const getAccessControlDisabledReason = (
    resourceType: AccessControlResourceType,
    minAccessLevel: AccessControlLevel,
    userAccessLevel?: AccessControlLevel,
    includeAccessDetails: boolean = true
): string | null => {
    // If the userAccessLevel is not provided, we use the app context for that resource type
    const parsedUserAccessLevel = userAccessLevel ?? getAppContext()?.resource_access_control?.[resourceType]

    // And if we can't figure out the user's access level from the arguments OR app context,
    // we assume they don't have access to the resource to err on the side of caution
    const hasAccess = parsedUserAccessLevel
        ? accessLevelSatisfied(resourceType, parsedUserAccessLevel, minAccessLevel)
        : false

    if (!hasAccess) {
        let reason = `You don't have sufficient permissions for this ${resourceTypeToString(resourceType)}.`
        if (includeAccessDetails) {
            reason += ` Your access level (${parsedUserAccessLevel ?? 'none'}) doesn't meet the required level (${minAccessLevel}).`
        }
        return reason
    }

    return null
}

/**
 * Simple boolean check to determine if a user has access to a resource.
 * Uses the access control disabled reason function and negates the result.
 *
 * @param resourceType - The type of resource being accessed
 * @param minAccessLevel - The minimum required access level
 * @param userAccessLevel - Optional user's current access level (falls back to app context)
 * @returns True if the user has sufficient access, false otherwise
 */
export const userHasAccess = (
    resourceType: AccessControlResourceType,
    minAccessLevel: AccessControlLevel,
    userAccessLevel?: AccessControlLevel
): boolean => {
    return !getAccessControlDisabledReason(resourceType, minAccessLevel, userAccessLevel)
}
