import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { warehouseLoginsLogic } from '../WarehouseAccessScene/warehouseLoginsLogic'

// pinned: the analytics event name in this file feeds dashboards, so renaming it breaks them.

function WarehouseConnectLoginSelectInner({
    value,
    onChange,
}: {
    value: string
    onChange: (username: string) => void
}): JSX.Element | null {
    const { logins } = useValues(warehouseLoginsLogic)
    // Logins come from an admin-only list. Until it loads, or when it fails, the snippets keep the root login.
    const usernames = (logins ?? []).filter((login) => !login.disabled).map((login) => login.username)

    if (usernames.length < 2) {
        return null
    }
    return (
        <div className="flex items-center gap-2">
            <Label>Login</Label>
            <Select
                items={usernames.map((username) => ({ label: username, value: username }))}
                value={value}
                onValueChange={(next) => {
                    if (typeof next === 'string') {
                        posthog.capture('warehouse connect login selected')
                        onChange(next)
                    }
                }}
            >
                <SelectTrigger size="sm" className="font-mono">
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {usernames.map((username) => (
                        <SelectItem key={username} value={username}>
                            {username}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

/** Lets an admin put one of the warehouse's logins into the snippets. Members get nothing and the logins logic never mounts for them. */
export function WarehouseConnectLoginSelect(props: {
    value: string
    onChange: (username: string) => void
}): JSX.Element | null {
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (adminRestrictionReason) {
        return null
    }
    return <WarehouseConnectLoginSelectInner {...props} />
}
