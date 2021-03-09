import { Tooltip } from 'antd'
import { useValues } from 'kea'
import React, { useMemo } from 'react'
import { organizationLogic } from '../../scenes/organizationLogic'
import { OrganizationMembershipLevel } from '../constants'

export interface RestrictedComponentProps {
    isRestricted: boolean
    restrictionReason: null | string
}

export interface RestrictedAreaProps {
    Component: (props: RestrictedComponentProps) => JSX.Element
    minimumAccessLevel: OrganizationMembershipLevel
}

export function RestrictedArea({ Component, minimumAccessLevel }: RestrictedAreaProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)

    const restrictionReason: null | string = useMemo(() => {
        if (!currentOrganization) {
            return 'Loading current organization…'
        }
        if (currentOrganization.membership_level === null) {
            return 'Your organization membership level is unknown.'
        }
        if (currentOrganization.membership_level < minimumAccessLevel) {
            if (minimumAccessLevel === OrganizationMembershipLevel.Owner) {
                return 'This area is restricted to the organization owner.'
            }
            return `This area is restricted to organization ${OrganizationMembershipLevel[minimumAccessLevel]}s and up. Your level is ${currentOrganization.membership_level}.`
        }
        return null
    }, [currentOrganization])

    return restrictionReason ? (
        <Tooltip title={restrictionReason}>
            <Component isRestricted={true} restrictionReason={restrictionReason} />
        </Tooltip>
    ) : (
        <Component isRestricted={false} restrictionReason={null} />
    )
}
