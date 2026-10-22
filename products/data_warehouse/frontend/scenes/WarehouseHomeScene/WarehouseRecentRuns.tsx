import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import {
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Empty,
    EmptyDescription,
    EmptyTitle,
    Item,
    ItemContent,
    ItemDescription,
    ItemGroup,
    ItemTitle,
    Skeleton,
    Text,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { PipelineActivityRowApi } from '../../generated/api.schemas'
import { warehouseHomeLogic } from './warehouseHomeLogic'

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const RUN_BADGES: Record<string, { label: string; variant: BadgeVariant }> = {
    Running: { label: 'Running', variant: 'info' },
    Completed: { label: 'Completed', variant: 'success' },
    Failed: { label: 'Failed', variant: 'destructive' },
    BillingLimitReached: { label: 'Billing limit reached', variant: 'warning' },
    BillingLimitTooLow: { label: 'Billing limit too low', variant: 'warning' },
}

function runUrl(run: PipelineActivityRowApi): string | null {
    if (run.source_id) {
        return urls.dataWarehouseSource(run.source_id, 'schemas')
    }
    return run.type === 'Materialized view' ? urls.models() : null
}

function RunRow({ run }: { run: PipelineActivityRowApi }): JSX.Element {
    const badge = RUN_BADGES[run.status] ?? { label: run.status, variant: 'default' as BadgeVariant }
    const to = runUrl(run)
    return (
        <Item
            size="xs"
            // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
            className={to ? 'text-foreground hover:bg-fill-hover hover:text-foreground' : undefined}
            {...(to
                ? {
                      render: (
                          <LinkPrimitive
                              to={to}
                              data-attr="warehouse-home-run"
                              onClick={() => {
                                  posthog.capture('warehouse overview link clicked', { target: 'run' })
                              }}
                          />
                      ),
                  }
                : {})}
        >
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{run.name ?? run.type ?? 'Run'}</ItemTitle>
                <ItemDescription>
                    {run.type ? `${run.type} · ` : ''}
                    <span translate="no">{dayjs(run.finished_at ?? run.created_at).fromNow()}</span>
                </ItemDescription>
            </ItemContent>
            <Badge variant={badge.variant}>{badge.label}</Badge>
        </Item>
    )
}

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
                    <RunRow key={run.id} run={run} />
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
