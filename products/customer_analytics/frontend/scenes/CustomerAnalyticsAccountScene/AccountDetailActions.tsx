import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountViewsLogic } from './accountViewsLogic'

interface AccountDetailActionsProps {
    projectId: number
}

export function AccountDetailActions({ projectId }: AccountDetailActionsProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const logic = accountViewsLogic({ projectId })
    const { accountDetailTabs, config, configError, configLoading } = useValues(logic)
    const { openConfigure, openCreateEditor } = useActions(logic)

    if (!featureFlags[FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]) {
        return null
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconGear />}
                data-attr="account-detail-configure-tabs"
                disabledReason={configLoading || (!config && !configError) ? 'Loading tab settings' : undefined}
                onClick={() => openConfigure(config && !configError ? accountDetailTabs : null)}
            >
                Configure tabs
            </LemonButton>
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPlus />}
                data-attr="account-detail-add-view"
                onClick={openCreateEditor}
            >
                New view
            </LemonButton>
        </>
    )
}
