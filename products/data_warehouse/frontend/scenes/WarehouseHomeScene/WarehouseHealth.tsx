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
    ItemGroup,
    Skeleton,
    Text,
} from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { WarehouseHealthIssueRow } from './WarehouseHealthIssueRow'
import { statusBadge } from './warehouseHealthStatus'
import { HEALTH_ISSUES_LIMIT, warehouseHomeLogic } from './warehouseHomeLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseHealth(): JSX.Element {
    const { warehouseIssues, issueCountsByStatus, healthIssuesFailed } = useValues(warehouseHomeLogic)
    const { loadWarehouseHomeHealthIssues } = useActions(warehouseHomeLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const viewAllUrl = featureFlags[FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION] ? urls.etlOverview() : urls.sources()

    let content: JSX.Element
    if (warehouseIssues === null && !healthIssuesFailed) {
        content = <Skeleton className="h-24 w-full" />
    } else if (healthIssuesFailed || warehouseIssues === null) {
        content = (
            <div className="flex flex-wrap items-center gap-2">
                <Text size="sm" variant="muted">
                    Couldn't load health issues.
                </Text>
                <Button onClick={() => loadWarehouseHomeHealthIssues()} data-attr="warehouse-home-health-retry">
                    Retry
                </Button>
            </div>
        )
    } else if (warehouseIssues.length === 0) {
        content = (
            <Empty>
                <EmptyTitle>All clear</EmptyTitle>
                <EmptyDescription>Every sync and view is healthy.</EmptyDescription>
            </Empty>
        )
    } else {
        content = (
            <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                    {issueCountsByStatus.map(([status, count]) => (
                        <Badge key={status} variant={statusBadge(status).variant}>
                            {`${count} ${statusBadge(status).label.toLowerCase()}`}
                        </Badge>
                    ))}
                </div>
                <ItemGroup>
                    {warehouseIssues.slice(0, HEALTH_ISSUES_LIMIT).map((issue) => (
                        <WarehouseHealthIssueRow key={`${issue.type}-${issue.id}`} issue={issue} />
                    ))}
                </ItemGroup>
                {warehouseIssues.length > HEALTH_ISSUES_LIMIT && (
                    <Button
                        variant="link"
                        nativeButton={false}
                        render={<LinkPrimitive to={viewAllUrl} />}
                        data-attr="warehouse-home-health-view-all"
                        onClick={() => {
                            posthog.capture('warehouse overview link clicked', { target: 'issues' })
                        }}
                    >
                        {`View all ${warehouseIssues.length} issues`}
                    </Button>
                )}
            </div>
        )
    }

    return (
        <Card>
            <CardHeader>
                <CardTitle>Health</CardTitle>
            </CardHeader>
            <CardContent>{content}</CardContent>
        </Card>
    )
}
