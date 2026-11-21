import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyTitle,
    ItemGroup,
    Skeleton,
    Text,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { warehouseHomeLogic } from './warehouseHomeLogic'
import { WarehouseRecentRunRow } from './WarehouseRecentRunRow'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseRecentRuns(): JSX.Element {
    const { recentRuns, recentRunsFailed } = useValues(warehouseHomeLogic)
    const { loadWarehouseHomeRecentRuns } = useActions(warehouseHomeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const viewAllUrl = featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION] ? urls.etlOverview() : urls.sources()

    let content: JSX.Element
    if (recentRuns === null && !recentRunsFailed) {
        content = <Skeleton className="h-24 w-full" />
    } else if (recentRunsFailed || recentRuns === null) {
        content = (
            <div className="flex flex-wrap items-center gap-2">
                <Text size="sm" variant="muted">
                    Couldn't load runs.
                </Text>
                <Button onClick={() => loadWarehouseHomeRecentRuns()} data-attr="warehouse-home-runs-retry">
                    Retry
                </Button>
            </div>
        )
    } else if (recentRuns.length === 0) {
        content = (
            <Empty>
                <EmptyTitle>No recent runs</EmptyTitle>
                <EmptyDescription>Syncs and view refreshes show up here once they run.</EmptyDescription>
            </Empty>
        )
    } else {
        content = (
            <ItemGroup>
                {recentRuns.map((run) => (
                    <WarehouseRecentRunRow key={run.id} run={run} />
                ))}
            </ItemGroup>
        )
    }

    return (
        <Card>
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
                <CardTitle>Recent runs</CardTitle>

                <Button
                    size="sm"
                    nativeButton={false}
                    render={<LinkPrimitive to={viewAllUrl} />}
                    data-attr="warehouse-home-runs-view-all"
                    onClick={() => {
                        posthog.capture('warehouse overview link clicked', { target: 'runs' })
                    }}
                >
                    View all
                </Button>
            </CardHeader>
            <CardContent>{content}</CardContent>
        </Card>
    )
}
