import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'
import { QuillNewCrossProjectDashboardButton } from './QuillNewCrossProjectDashboardButton'

/** The page header action wherever the cross-project list shows. The list renders the modal it opens. */
export function NewCrossProjectDashboardButton(): JSX.Element {
    const { openNewModal } = useActions(crossProjectDashboardsListLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return <QuillNewCrossProjectDashboardButton />
    }

    return (
        <LemonButton type="primary" size="small" onClick={openNewModal} data-attr="cross-project-dashboard-new">
            New cross-project dashboard
        </LemonButton>
    )
}
