import { useActions } from 'kea'

import { IconDashboard } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { dashboardV2Logic } from './dashboardV2Logic'

export function DashboardV2EmptyState(): JSX.Element {
    const { openJsonDialog } = useActions(dashboardV2Logic)

    return (
        <Empty data-attr="dashboard-v2-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-dashboards-light)">
                        <IconDashboard />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>No panels yet</EmptyTitle>
                <EmptyDescription>This dashboard has no panels. Add them by editing its JSON.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" onClick={() => openJsonDialog()} data-attr="dashboard-v2-empty-edit-json">
                    Edit as JSON
                </Button>
            </EmptyContent>
        </Empty>
    )
}
