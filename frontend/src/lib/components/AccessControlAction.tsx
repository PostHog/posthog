import React from 'react'

import { getAppContext } from 'lib/utils/getAppContext'

import { AccessControlResourceType } from '~/types'

type AccessControlLevelNone = 'none'
type AccessControlLevelMember = AccessControlLevelNone | 'member' | 'admin'
type AccessControlLevelResource = AccessControlLevelNone | 'viewer' | 'editor' | 'manager'
type AccessControlLevel = AccessControlLevelMember | AccessControlLevelResource

const orderedAccessLevels = (resourceType: AccessControlResourceType): AccessControlLevel[] => {
    if (resourceType === AccessControlResourceType.Project || resourceType === AccessControlResourceType.Organization) {
        return ['none', 'member', 'admin']
    }
    return ['none', 'viewer', 'editor', 'manager']
}

export const resourceTypeToString = (resourceType: AccessControlResourceType): string => {
    if (resourceType === AccessControlResourceType.RevenueAnalytics) {
        return 'revenue analytics resource'
    }

    return resourceType.replace('_', ' ')
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

export const userHasAccess = (
    resourceType: AccessControlResourceType,
    minAccessLevel: AccessControlLevel,
    userAccessLevel?: AccessControlLevel
): boolean => {
    return !getAccessControlDisabledReason(resourceType, minAccessLevel, userAccessLevel)
}

interface AccessControlActionChildrenProps {
    disabled?: boolean
    disabledReason: string | null
}

interface AccessControlActionProps<P extends AccessControlActionChildrenProps> {
    children: React.ComponentType<P> | React.ReactElement<P>
    resourceType: AccessControlResourceType
    minAccessLevel: AccessControlLevel
    userAccessLevel?: AccessControlLevel
}

// This is a wrapper around a component that checks if the user has access to the resource
// and if not, it sets the `disabled` and `disabledReason` props on the child component
//
// NOTE: TS is not powerful enough to enforce the fact that the child component *must* receive
// the `disabled` and `disabledReason` props. This means we are accepting any component and
// then setting the props at runtime even in case they "shouldn't" receive them.
// This is not problematic during runtime but it's admitedly slightly confusing
export function AccessControlAction<P extends AccessControlActionChildrenProps>({
    children,
    resourceType,
    minAccessLevel,
    userAccessLevel,
}: AccessControlActionProps<P>): JSX.Element {
    const disabledReason = getAccessControlDisabledReason(resourceType, minAccessLevel, userAccessLevel)

    // Check if children is a component function or a rendered element
    // If it's a component function, we need to render it with the props
    if (typeof children === 'function') {
        const Component = children as React.ComponentType<P>
        const componentProps = {
            disabled: !!disabledReason,
            disabledReason: disabledReason,
        } as P

        return <Component {...componentProps} />
    }

    // If it's a rendered element, we need to clone it overloading the props
    const element = children as React.FunctionComponentElement<P>
    return React.cloneElement<P>(element, {
        disabled: element.props.disabled ?? !!disabledReason,
        disabledReason: element.props.disabledReason ?? disabledReason,
    } as Partial<P>)
}
