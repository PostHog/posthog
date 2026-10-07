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
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import type { DataHealthIssueApi } from '../../generated/api.schemas'
import { HEALTH_ISSUES_LIMIT, warehouseHomeLogic } from './warehouseHomeLogic'

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const STATUS_BADGES: Record<string, { label: string; variant: BadgeVariant }> = {
    failed: { label: 'Failed', variant: 'destructive' },
    billing_limit: { label: 'Billing limit', variant: 'warning' },
    degraded: { label: 'Degraded', variant: 'warning' },
    disabled: { label: 'Disabled', variant: 'default' },
}

const TYPE_LABELS: Record<string, string> = {
    external_data_sync: 'Sync',
    source: 'Source',
    materialized_view: 'View',
}

function statusBadge(status: string): { label: string; variant: BadgeVariant } {
    return STATUS_BADGES[status] ?? { label: status, variant: 'default' }
}

function IssueRow({ issue }: { issue: DataHealthIssueApi }): JSX.Element {
    const badge = statusBadge(issue.status)
    const typeLabel = TYPE_LABELS[issue.type] ?? issue.type
    return (
        <Item
            size="xs"
            // The app styles every link in its accent color. A whole-row link reads as a row, so it keeps the text color.
            className={issue.url ? 'text-foreground hover:bg-fill-hover hover:text-foreground' : undefined}
            {...(issue.url
                ? {
                      render: (
                          <LinkPrimitive
                              to={issue.url}
                              data-attr="warehouse-home-health-issue"
                              onClick={() => {
                                  posthog.capture('warehouse overview link clicked', { target: 'issue' })
                              }}
                          />
                      ),
                  }
                : {})}
        >
            <ItemContent className="min-w-0">
                <ItemTitle className="truncate">{issue.name}</ItemTitle>
                <ItemDescription>
                    {typeLabel}
                    {issue.source_type ? ` · ${issue.source_type}` : ''}
                </ItemDescription>
            </ItemContent>
            <Badge variant={badge.variant}>{badge.label}</Badge>
        </Item>
    )
}

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
                            {count} {statusBadge(status).label.toLowerCase()}
                        </Badge>
                    ))}
                </div>
                <ItemGroup>
                    {warehouseIssues.slice(0, HEALTH_ISSUES_LIMIT).map((issue) => (
                        <IssueRow key={`${issue.type}-${issue.id}`} issue={issue} />
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
                        View all {warehouseIssues.length} issues
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
