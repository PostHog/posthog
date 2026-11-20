import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Button, Empty, EmptyDescription, EmptyHeader, EmptyTitle, Skeleton } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { warehouseConsoleLogic } from './warehouseConsoleLogic'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

/** What a console page shows until the warehouse is ready: loading, error, no warehouse and not ready are four different states. */
export function WarehouseConsoleState({ page }: { page: string }): JSX.Element | null {
    const { consoleState } = useValues(warehouseConsoleLogic)
    const { loadWarehouseStatus } = useActions(warehouseConsoleLogic)

    if (consoleState === 'ready') {
        return null
    }
    if (consoleState === 'loading') {
        return <Skeleton className="h-32 w-full" />
    }
    if (consoleState === 'error') {
        return (
            <Empty>
                <EmptyHeader>
                    <EmptyTitle>Couldn't load your warehouse</EmptyTitle>
                    <EmptyDescription>Check your connection and try again.</EmptyDescription>
                </EmptyHeader>
                <Button
                    onClick={() => {
                        posthog.capture('warehouse console retry clicked', { page })
                        loadWarehouseStatus()
                    }}
                    data-attr="warehouse-console-retry"
                >
                    Try again
                </Button>
            </Empty>
        )
    }
    return (
        <Empty>
            <EmptyHeader>
                <EmptyTitle>
                    {consoleState === 'no_warehouse' ? 'No managed warehouse yet' : 'Warehouse not ready yet'}
                </EmptyTitle>
                <EmptyDescription>
                    {consoleState === 'no_warehouse'
                        ? 'Set up your managed warehouse in Data ops first. This page works once it is ready.'
                        : 'Your warehouse is still being set up, or its query engine is not ready. Check its status in Data ops.'}
                </EmptyDescription>
            </EmptyHeader>
            <Button
                variant="primary"
                nativeButton={false}
                render={<LinkPrimitive to={urls.dataOps('settings')} />}
                onClick={() => {
                    posthog.capture('warehouse console data ops clicked', { page, state: consoleState })
                }}
                data-attr="warehouse-console-open-data-ops"
            >
                Open Data ops
            </Button>
        </Empty>
    )
}
