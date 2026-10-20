import { useActions } from 'kea'

import { Button } from '@posthog/quill'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'

export function QuillNewCrossProjectDashboardButton(): JSX.Element {
    const { openNewModal } = useActions(crossProjectDashboardsListLogic)

    return (
        <Button variant="primary" onClick={openNewModal} data-attr="cross-project-dashboard-new">
            New cross-project dashboard
        </Button>
    )
}
