import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'

/** The page header action wherever the cross-project list shows. The list renders the modal it opens. */
export function NewCrossProjectDashboardButton(): JSX.Element {
    const { openNewModal } = useActions(crossProjectDashboardsListLogic)

    return (
        <LemonButton type="primary" size="small" onClick={openNewModal} data-attr="cross-project-dashboard-new">
            New cross-project dashboard
        </LemonButton>
    )
}
