import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { mentionRolesLogic } from './mentionRolesLogic'

export const RichContentRoleMention = ({ id }: { id: string }): JSX.Element => {
    const { roles } = useValues(mentionRolesLogic)
    const { ensureRolesLoaded } = useActions(mentionRolesLogic)

    useEffect(() => {
        ensureRolesLoaded()
    }, [ensureRolesLoaded])

    const role = roles.find((role) => role.id === id)

    return (
        <Tooltip
            title={role ? `Role with ${role.members.length} ${role.members.length === 1 ? 'member' : 'members'}` : null}
        >
            <span className="ph-no-capture bg-fill-highlight-100 px-1 rounded font-medium">
                @{role?.name ?? '(Role)'}
            </span>
        </Tooltip>
    )
}
