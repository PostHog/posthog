import React from 'react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

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
