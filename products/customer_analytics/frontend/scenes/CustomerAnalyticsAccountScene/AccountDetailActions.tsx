import { useActions, useValues } from 'kea'

import { IconGear, IconPlus } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { accountViewsLogic } from './accountViewsLogic'
import { QuillAccountDetailActions } from './QuillAccountDetailActions'

interface AccountDetailActionsProps {
    projectId: number
}

export function AccountDetailActions({ projectId }: AccountDetailActionsProps): JSX.Element {
    const logic = accountViewsLogic({ projectId })
    const { accountDetailTabs, config, configError, configLoading } = useValues(logic)
    const { openConfigure, openCreateEditor } = useActions(logic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillAccountDetailActions projectId={projectId} />
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
