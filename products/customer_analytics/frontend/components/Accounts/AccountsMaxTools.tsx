import { useActions } from 'kea'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { accountsLogic } from './accountsLogic'
import { accountsViewsLogic } from './accountsViewsLogic'
import type { AccountSystemTabKind } from './accountViewComponents'

interface OpenAccountResult {
    account_id?: string
    account_name?: string
    external_id?: string | null
    tab?: AccountSystemTabKind
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
            accountsViewsLogic.findMounted()?.actions.prepareAccountReturn()
            openAccount(result.account_id, result.tab ?? 'usage')
        },
    })

    return null
}
