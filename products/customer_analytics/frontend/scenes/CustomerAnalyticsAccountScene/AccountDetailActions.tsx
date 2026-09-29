import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountViewsLogic } from './accountViewsLogic'

interface AccountDetailActionsProps {
    projectId: number
}

export function AccountDetailActions({ projectId }: AccountDetailActionsProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openCreateEditor } = useActions(accountViewsLogic({ projectId }))

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]) {
        return null
    }

    return (
        <LemonButton
            type="primary"
            size="small"
            icon={<IconPlus />}
            data-attr="account-detail-add-view"
            onClick={openCreateEditor}
        >
            New view
        </LemonButton>
    )
}
