import { IconDashboard } from '@posthog/icons'
import {
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { NewDashboardV2Button } from './NewDashboardV2Button'

export function DashboardV2ListEmptyState(): JSX.Element {
    return (
        <Empty data-attr="dashboard-v2-list-empty">
            <EmptyHeader>
                <IconStack>
                    <IconStackItem color="var(--color-product-dashboards-light)">
                        <IconDashboard />
                    </IconStackItem>
                </IconStack>
                <EmptyTitle>No dashboards yet</EmptyTitle>
                <EmptyDescription>Create a dashboard, or import one from JSON.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <NewDashboardV2Button />
            </EmptyContent>
        </Empty>
    )
}
