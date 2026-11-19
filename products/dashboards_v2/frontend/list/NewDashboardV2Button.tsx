import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { dashboardV2ListLogic } from './dashboardV2ListLogic'

export function NewDashboardV2Button(): JSX.Element {
    const { setNewDialogOpen } = useActions(dashboardV2ListLogic)

    return (
        <Button variant="primary" onClick={() => setNewDialogOpen(true)} data-attr="dashboard-v2-new">
            <IconPlus />
            New dashboard
        </Button>
    )
}
