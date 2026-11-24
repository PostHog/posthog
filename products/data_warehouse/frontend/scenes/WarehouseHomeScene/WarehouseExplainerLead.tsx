import posthog from 'posthog-js'

import { Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

// pinned: the data-attr value and analytics event name in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseExplainerLead(): JSX.Element {
    return (
        <div className="flex max-w-2xl flex-col gap-3">
            <Text size="sm">
                The managed warehouse stores your PostHog data and the tables from your sources in one place that you
                can query with SQL. One warehouse is shared by every project in your organization.
            </Text>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <Button
                    variant="primary"
                    nativeButton={false}
                    render={<LinkPrimitive to={urls.warehouseSettings()} />}
                    onClick={() => posthog.capture('warehouse explainer set up clicked')}
                    data-attr="warehouse-explainer-set-up"
                >
                    Set up warehouse
                </Button>
                <Text size="xs" variant="muted">
                    Setup takes a few minutes.
                </Text>
            </div>
        </div>
    )
}
