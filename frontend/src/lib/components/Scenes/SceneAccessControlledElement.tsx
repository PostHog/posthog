import { AccessControlResourceType, WithAccessControl } from '~/types'
import { AccessControlAction } from '../AccessControlAction'

type SceneAccessControlledElementProps = {
    userAccessLevel?: WithAccessControl['user_access_level']
    minAccessLevel: WithAccessControl['user_access_level']
    resourceType: AccessControlResourceType
    children: (accessControlDisabledReason?: string) => React.ReactNode
}

export function SceneAccessControlledElement({
    children,
    resourceType,
    minAccessLevel,
    userAccessLevel,
}: SceneAccessControlledElementProps): JSX.Element {
    return (
        <AccessControlAction
            userAccessLevel={userAccessLevel}
            minAccessLevel={minAccessLevel}
            resourceType={resourceType}
        >
            {({ disabledReason: accessControlDisabledReason }) => {
                return <>{children(accessControlDisabledReason ?? undefined)}</>
            }}
        </AccessControlAction>
    )
}
