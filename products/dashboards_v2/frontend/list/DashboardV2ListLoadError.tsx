import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { dashboardV2ListLogic } from './dashboardV2ListLogic'

export function DashboardV2ListLoadError(): JSX.Element {
    const { dashboardPageLoading, search } = useValues(dashboardV2ListLogic)
    const { loadDashboards } = useActions(dashboardV2ListLogic)

    return (
        <Empty data-attr="dashboard-v2-list-load-error">
            <EmptyHeader>
                <EmptyMedia variant="icon">
                    <IconWarning />
                </EmptyMedia>
                <EmptyTitle>Couldn't load dashboards</EmptyTitle>
                <EmptyDescription>Try again. If it keeps happening, contact support.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>
                <Button variant="outline" loading={dashboardPageLoading} onClick={() => loadDashboards(search)}>
                    Try again
                </Button>
            </EmptyContent>
        </Empty>
    )
}
