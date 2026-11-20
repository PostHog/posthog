import { useValues } from 'kea'

import { Button, Card, CardContent, CardHeader, CardTitle, Skeleton, Text } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { warehouseConsoleOverviewLogic } from './warehouseConsoleOverviewLogic'
import { WarehouseHomeLink } from './WarehouseHomeLink'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseLiveWorkload(): JSX.Element {
    const { workload, workloadSnapshotLoading, workloadFailed, workloadSnapshot } =
        useValues(warehouseConsoleOverviewLogic)

    let body: JSX.Element
    if (!workloadSnapshot) {
        body = workloadFailed ? (
            <Text size="sm" variant="muted">
                Couldn't load live queries. This refreshes on its own.
            </Text>
        ) : workloadSnapshotLoading ? (
            <Skeleton className="h-10 w-full" />
        ) : (
            <></>
        )
    } else if (!workload) {
        body = (
            <Text size="sm" variant="muted">
                Live query data is unavailable right now.
            </Text>
        )
    } else {
        body = (
            <div className="flex flex-wrap gap-x-6 gap-y-1">
                <div>
                    <Text size="lg" weight="semibold" render={<div />}>
                        {workload.running}
                    </Text>
                    <Text size="xs" variant="muted" render={<div />}>
                        Running
                    </Text>
                </div>
                <div>
                    <Text size="lg" weight="semibold" render={<div />}>
                        {workload.queued}
                    </Text>
                    <Text size="xs" variant="muted" render={<div />}>
                        Queued
                    </Text>
                </div>
            </div>
        )
    }
    return (
        <Card data-attr="warehouse-home-live-workload">
            <CardHeader>
                <CardTitle>Live workload</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {body}
                <div>
                    <Button
                        size="sm"
                        nativeButton={false}
                        render={
                            <WarehouseHomeLink
                                to={urls.warehouseQueries()}
                                section="live_workload"
                                data-attr="warehouse-home-open-queries"
                            >
                                See queries
                            </WarehouseHomeLink>
                        }
                    />
                </div>
            </CardContent>
        </Card>
    )
}
