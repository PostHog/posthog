import { useActions } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { AccountExpansionTab } from './accountsExpansionLogic'
import { accountsLogic } from './accountsLogic'

interface OpenAccountResult {
    account_id?: string
    account_name?: string
    external_id?: string | null
    tab?: AccountExpansionTab
    error?: string
}

export function AccountsMaxTools(): JSX.Element | null {
    const { openAccount } = useActions(accountsLogic)

    useMaxTool({
        identifier: 'open_account',
        context: {},
        callback: (result: OpenAccountResult) => {
            if (result?.error || !result.account_id) {
                lemonToast.error("Couldn't open that account.")
                return
            }
            openAccount(result.account_id, result.external_id ?? null, result.account_name ?? '', result.tab ?? 'usage')
        },
    })

    return null
}
