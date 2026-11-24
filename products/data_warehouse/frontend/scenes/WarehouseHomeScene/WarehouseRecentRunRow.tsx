import posthog from 'posthog-js'

import { Badge, Item, ItemContent, ItemDescription, ItemTitle } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { PipelineActivityRowApi } from '../../generated/api.schemas'
import type { BadgeVariant } from './warehouseHealthStatus'

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

export function WarehouseRecentRunRow({ run }: { run: PipelineActivityRowApi }): JSX.Element {
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
                    {run.type && <span>{`${run.type} · `}</span>}
                    <span translate="no">{dayjs(run.finished_at ?? run.created_at).fromNow()}</span>
                </ItemDescription>
            </ItemContent>
            <Badge variant={badge.variant}>{badge.label}</Badge>
        </Item>
    )
}
