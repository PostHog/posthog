import { LemonButton } from '@posthog/lemon-ui'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

function openWorkInProgressDialog(title: string): void {
    LemonDialog.open({
        title,
        content: 'This feature is a work in progress.',
    })
}

export function AccountDetailActions(): JSX.Element {
    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                data-attr="account-detail-configure-tabs"
                onClick={() => openWorkInProgressDialog('Configure tabs')}
            >
                Configure tabs
            </LemonButton>
            <LemonButton
                type="primary"
                size="small"
                data-attr="account-detail-add-view"
                onClick={() => openWorkInProgressDialog('Add view')}
            >
                Add view
            </LemonButton>
        </>
    )
}
