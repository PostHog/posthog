import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { dashboardV2Logic } from './dashboardV2Logic'

export function DashboardV2LoadError(): JSX.Element {
    const { dashboardLoading } = useValues(dashboardV2Logic)
    const { loadDashboard } = useActions(dashboardV2Logic)

    return (
        <Empty data-attr="dashboard-v2-load-error">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconWarning />
                </EmptyMedia>
                <EmptyTitle>Couldn't load this dashboard</EmptyTitle>
                <EmptyDescription>Try again. If it keeps happening, contact support.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" loading={dashboardLoading} onClick={() => loadDashboard()}>
                    Try again
                </Button>
            </EmptyContent>
        </Empty>
    )
}
