import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccountsOverviewTilesEditor } from './AccountsOverviewTilesEditor'
import { accountsOverviewTilesLogic } from './accountsOverviewTilesLogic'

export function AccountsOverviewTilesButton(): JSX.Element {
    const { editorVisible } = useValues(accountsOverviewTilesLogic)
    const { showEditor, hideEditor } = useActions(accountsOverviewTilesLogic)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconGear />}
                onClick={showEditor}
                data-attr="accounts-overview-tiles-edit"
            >
                Edit overview tiles
            </LemonButton>
            <AccountsOverviewTilesEditor isOpen={editorVisible} onClose={hideEditor} />
        </>
    )
}
