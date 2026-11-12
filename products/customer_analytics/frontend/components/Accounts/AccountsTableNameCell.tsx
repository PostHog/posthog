import posthog from 'posthog-js'
import type { MouseEventHandler } from 'react'

import { ProfilePicture, Tooltip } from '@posthog/lemon-ui'

import type { AccountPresenceViewerApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountNameCell } from './AccountNameCell'
import { accountsViewsLogic } from './accountsViewsLogic'
import { AccountsEvents } from './constants'

export interface AccountsTableNameCellProps {
    accountId?: string
    externalId?: string | null
    logoDomain?: string | null
    name: string
    viewers: AccountPresenceViewerApi[]
}

const MAX_PRESENCE_AVATARS = 3

function formatViewerNames(names: string[]): string {
    if (names.length === 1) {
        return names[0] ?? ''
    }
    if (names.length === 2) {
        return `${names[0]} and ${names[1]}`
    }
    return `${names.slice(0, -1).join(', ')}, and ${names.at(-1) ?? ''}`
}

export function AccountsTableNameCell({
    accountId,
    externalId,
    logoDomain,
    name,
    viewers,
}: AccountsTableNameCellProps): JSX.Element {
    const handleClick: MouseEventHandler<HTMLElement> = (event) => {
        if (!accountId || event.metaKey || event.ctrlKey || event.shiftKey) {
            return
        }

        accountsViewsLogic.findMounted()?.actions.prepareAccountReturn()
        posthog.capture(AccountsEvents.AccountOpened)
    }

    const shownViewers = viewers.slice(0, MAX_PRESENCE_AVATARS)
    const tooltip = `${formatViewerNames(viewers.map((viewer) => viewer.display_name))} ${
        viewers.length === 1 ? 'is' : 'are'
    } viewing this account`

    return (
        <div className="flex items-center gap-2">
            <AccountNameCell
                accountId={accountId}
                name={name}
                externalId={externalId}
                logoDomain={logoDomain}
                onClick={handleClick}
            />
            {shownViewers.length ? (
                <Tooltip title={tooltip}>
                    <div className="ProfileBubbles shrink-0" aria-label={tooltip}>
                        {shownViewers.map((viewer, index) => (
                            <ProfilePicture
                                key={viewer.user_id}
                                name={viewer.display_name}
                                title={viewer.display_name}
                                size="sm"
                                index={index}
                            />
                        ))}
                        {viewers.length > shownViewers.length ? (
                            <div className="ProfileBubbles__more">+{viewers.length - shownViewers.length}</div>
                        ) : null}
                    </div>
                </Tooltip>
            ) : null}
        </div>
    )
}
