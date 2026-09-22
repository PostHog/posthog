import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { openAccountDetailWorkInProgress } from './accountDetailWorkInProgress'

export function AccountDetailActions(): JSX.Element {
    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconGear />}
                data-attr="account-detail-configure-tabs"
                onClick={() => openAccountDetailWorkInProgress('Configure tabs')}
            >
                Configure tabs
            </LemonButton>
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlus />}
                data-attr="account-detail-add-view"
                onClick={() => openAccountDetailWorkInProgress('Add view')}
            >
                Add view
            </LemonButton>
        </>
    )
}
