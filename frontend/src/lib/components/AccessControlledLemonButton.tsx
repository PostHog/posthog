import { LemonButton, LemonButtonProps } from 'lib/lemon-ui/LemonButton'

import { AccessControlResourceType, WithAccessControl } from '../../types'
import { AccessControlAction } from './AccessControlAction'

export type AccessControlledLemonButtonProps = LemonButtonProps & {
    userAccessLevel?: WithAccessControl['user_access_level']
    minAccessLevel: WithAccessControl['user_access_level']
    resourceType: AccessControlResourceType
}

export const AccessControlledLemonButton = ({
    userAccessLevel,
    minAccessLevel,
    resourceType,
    children,
    ...props
}: AccessControlledLemonButtonProps): JSX.Element => {
    return (
        <AccessControlAction
            userAccessLevel={userAccessLevel}
            minAccessLevel={minAccessLevel}
            resourceType={resourceType}
        >
            {({ disabledReason: accessControlDisabledReason }) => (
                <LemonButton {...props} disabledReason={accessControlDisabledReason || props.disabledReason}>
                    {children}
                </LemonButton>
            )}
        </AccessControlAction>
    )
}
