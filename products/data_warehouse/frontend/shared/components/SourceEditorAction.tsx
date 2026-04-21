import React from 'react'

import { AccessControlAction, AccessControlActionChildrenProps } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType, ExternalDataSource } from '~/types'

/**
 * Gates children on Editor access for an external data source — used consistently across schema
 * and source settings UI so that viewers see the control as disabled with a clear reason.
 */
export function SourceEditorAction({
    source,
    children,
}: {
    source: ExternalDataSource | null
    children:
        | React.ComponentType<AccessControlActionChildrenProps>
        | React.ReactElement<AccessControlActionChildrenProps>
}): JSX.Element {
    return (
        <AccessControlAction
            resourceType={AccessControlResourceType.ExternalDataSource}
            minAccessLevel={AccessControlLevel.Editor}
            userAccessLevel={source?.user_access_level}
        >
            {children}
        </AccessControlAction>
    )
}
