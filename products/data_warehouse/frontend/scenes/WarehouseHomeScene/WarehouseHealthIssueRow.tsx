import posthog from 'posthog-js'

import { Badge, Item, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { DataHealthIssueApi } from '../../generated/api.schemas'
import { statusBadge } from './warehouseHealthStatus'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const TYPE_LABELS: Record<string, string> = {
    external_data_sync: 'Sync',
    source: 'Source',
    materialized_view: 'View',
}

export function WarehouseHealthIssueRow({ issue }: { issue: DataHealthIssueApi }): JSX.Element {
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
                    {issue.source_type ? `${typeLabel} · ${issue.source_type}` : typeLabel}
                </ItemDescription>
            </ItemContent>
            <Badge variant={badge.variant}>{badge.label}</Badge>
        </Item>
    )
}
