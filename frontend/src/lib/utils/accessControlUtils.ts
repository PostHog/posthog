import posthog from 'posthog-js'

import { getAppContext } from 'lib/utils/getAppContext'
import { toSentenceCase } from 'lib/utils/strings'
import { Scene, sceneToAccessControlResourceType } from 'scenes/sceneTypes'

import { APIScopeObject, AccessControlLevel, AccessControlResourceType, AvailableFeature } from '~/types'

/** Which iteration of the access control settings UI an interaction came from. */
export type AccessControlUIVersion = 'v1' | 'v2'

/**
 * Capture an access control analytics event. All events are tagged with
 * `platform_feature: ACCESS_CONTROL` so usage of the feature can be grouped and
 * filtered together, matching the tagging used elsewhere (e.g. RestrictedArea).
 */
export const captureAccessControlEvent = (event: string, properties?: Record<string, unknown>): void => {
    posthog.capture(event, {
        ...properties,
        platform_feature: AvailableFeature.ACCESS_CONTROL,
    })
}

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
 * Returns the maximum allowed access level for a resource.
 * Matches the backend maximum_access_level function in user_access_control.py
 *
 * @param resource - The API scope object to check maximum access for
 * @returns The maximum access level required, or null if no maximum is set
 */
export const getMaximumAccessLevel = (resource: APIScopeObject): AccessControlLevel | null => {
    if (resource === AccessControlResourceType.ActivityLog) {
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
    if (resource === AccessControlResourceType.CustomerAnalytics) {
        return 'customer analytics'
    } else if (resource === AccessControlResourceType.LlmAnalytics) {
        return 'AI observability'
    } else if (resource === AccessControlResourceType.RevenueAnalytics) {
        return 'revenue analytics'
    } else if (resource === AccessControlResourceType.WebAnalytics) {
        return 'web analytics'
    } else if (resource === AccessControlResourceType.ActivityLog) {
        return 'activity logs'
    } else if (resource === AccessControlResourceType.ExternalDataSource) {
        return 'data warehouse sources'
    } else if (resource === AccessControlResourceType.WarehouseObjects) {
        // Umbrella label for warehouse tables + views (both inherit from this)
        return 'data warehouse tables & views'
    } else if (resource === AccessControlResourceType.Logs) {
        return 'logs'
    } else if (resource === AccessControlResourceType.Tracing) {
        return 'tracing'
    } else if (resource === AccessControlResourceType.SharingConfiguration) {
        return 'sharing'
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
    if (resourceType === AccessControlResourceType.ActivityLog) {
        return [AccessControlLevel.None, AccessControlLevel.Viewer]
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
    if (resourceType === AccessControlResourceType.CustomerAnalytics) {
        return 'customer analytics resource'
    } else if (resourceType === AccessControlResourceType.LlmAnalytics) {
        return 'AI observability resource'
    } else if (resourceType === AccessControlResourceType.RevenueAnalytics) {
        return 'revenue analytics resource'
    } else if (resourceType === AccessControlResourceType.WebAnalytics) {
        return 'web analytics resource'
    } else if (resourceType === AccessControlResourceType.ExternalDataSource) {
        return 'data warehouse source'
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
        let reason: string
        if (resourceType === AccessControlResourceType.WarehouseObjects) {
            // warehouse_objects is the umbrella scope id; the label users see in the picker is
            // "Data warehouse tables & views". Use it verbatim here for clarity.
            reason = `Requires ${toSentenceCase(minAccessLevel)} access to Data warehouse tables & views.`
        } else {
            reason = `You don't have sufficient permissions for this ${resourceTypeToString(resourceType)}.`
        }
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

/** Entry/search-result types mapped to the resource type gating them - identity for types that
 * are access control resources themselves, plus the backend's RESOURCE_INHERITANCE_MAP entries
 * for types that appear in trees and search. */
const ENTRY_TYPE_TO_RESOURCE_TYPE: Record<string, AccessControlResourceType> = {
    ...Object.fromEntries(Object.values(AccessControlResourceType).map((value) => [value, value])),
    session_recording_playlist: AccessControlResourceType.SessionRecording,
}

const productHasEffectiveNoneAccess = (resourceType: AccessControlResourceType): boolean => {
    return getAppContext()?.effective_resource_access_control?.[resourceType] === AccessControlLevel.None
}

/**
 * Disabled reason for a product navigation item (sidebar product list, search product results)
 * when the user's effective access to the product's resource is "none".
 *
 * Mirrors the scene gating in sceneLogic (which uses `effective_resource_access_control` and
 * `sceneToAccessControlResourceType`), so items are disabled exactly when opening the target
 * page would show "Access denied". Users with object-level grants get effective "viewer"
 * access, so the product stays enabled for them.
 *
 * @param item - Navigation item with the scene key it points at (e.g. a FileSystemImport)
 * @returns Reason to show on the disabled item, or undefined when the user has access
 */
export const getProductAccessDisabledReason = (item: {
    sceneKey?: string
    path?: string
    displayLabel?: string
}): string | undefined => {
    if (!item.sceneKey) {
        return undefined
    }
    const resourceType = sceneToAccessControlResourceType[item.sceneKey as Scene]
    if (!resourceType || !productHasEffectiveNoneAccess(resourceType)) {
        return undefined
    }
    return `You don't have access to ${item.displayLabel || item.path || 'this product'}`
}

/**
 * Disabled reason for an individual item (search result, Files/Starred entry).
 *
 * Uses the backend-resolved access level for the underlying object, which accounts for
 * object-level overrides - an item the user was individually granted access to stays enabled
 * even when they have "none" access to the product. Additionally checks the product's
 * effective access: when it is "none" the scene gate denies every item of that type,
 * including ones the user created (object creators keep object-level access but aren't
 * reflected in the effective map), so those must be disabled too or clicking them would
 * still land on "Access denied".
 *
 * @param entry - Entry carrying the backend-resolved `user_access_level` and its type
 * @returns Reason to show on the disabled item, or undefined when the user has access
 */
export const getEntryAccessDisabledReason = (entry: {
    user_access_level?: string | null
    type?: string | null
}): string | undefined => {
    const resourceType = entry.type ? ENTRY_TYPE_TO_RESOURCE_TYPE[entry.type] : undefined
    const blockedByProduct = resourceType !== undefined && productHasEffectiveNoneAccess(resourceType)
    if (!blockedByProduct && entry.user_access_level !== AccessControlLevel.None) {
        return undefined
    }
    return `You don't have access to ${entry.type ? `this ${entry.type.replace(/_/g, ' ')}` : 'this item'}`
}

/**
 * Returns a tooltip message for a resource type if it has special access control behavior.
 * Use this to inform users about resource-specific access control limitations or clarifications.
 *
 * @param resource - The API scope object to get tooltip text for
 * @returns Tooltip text describing special access control behavior, or null if no special behavior
 */
export const getAccessControlTooltip = (resource: APIScopeObject): string | null => {
    if (resource === AccessControlResourceType.ExternalDataSource) {
        return 'Access control only applies to managed sources (Stripe, Postgres, etc.) and covers CRUD operations on the source configuration. It does not restrict querying data from those sources.'
    }
    if (resource === AccessControlResourceType.WarehouseObjects) {
        return 'Viewer is required to query a table or view via SQL. Editor and above also control creating, editing, and deleting tables, views (aka "models"), folders, and joins.'
    }
    if (resource === AccessControlResourceType.SharingConfiguration) {
        return 'Controls whether users can share resources like dashboards, insights, etc. with anyone via a public link.'
    }
    return null
}
