import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import type { MouseEventHandler } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccountNameCell } from './AccountNameCell'
import { accountsExpansionLogic } from './accountsExpansionLogic'
import { AccountsEvents } from './constants'

export interface AccountsTableNameCellProps {
    accountId?: string
    externalId?: string | null
    logoDomain?: string | null
    name: string
}

export function AccountsTableNameCell({
    accountId,
    externalId,
    logoDomain,
    name,
}: AccountsTableNameCellProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { isAccountExpanded } = useValues(accountsExpansionLogic)
    const { toggleAccountExpanded } = useActions(accountsExpansionLogic)
    const accountSceneEnabled = !!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_SCENE]

    const handleClick: MouseEventHandler<HTMLElement> = (event) => {
        if (!accountId || event.metaKey || event.ctrlKey || event.shiftKey) {
            return
        }

        if (accountSceneEnabled) {
            posthog.capture(AccountsEvents.AccountOpened)
            return
        }

        event.preventDefault()
        event.stopPropagation()
        if (!isAccountExpanded(accountId)) {
            posthog.capture(AccountsEvents.AccountOpened)
        }
        toggleAccountExpanded(accountId)
    }

    return (
        <AccountNameCell
            accountId={accountId}
            name={name}
            externalId={externalId}
            logoDomain={logoDomain}
            onClick={handleClick}
        />
    )
}
