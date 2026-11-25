import posthog from 'posthog-js'

import { Button, Card, Heading, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { WarehouseExplainerFlow } from './WarehouseExplainerFlow'

// pinned: the data-attr value and analytics event name in this file feed autocapture and dashboards, so renaming them breaks both.

/** The top of the explainer: what the warehouse is, the one action, and a picture of how data moves through it. */
export function WarehouseExplainerHero(): JSX.Element {
    return (
        <Card size="sm" data-attr="warehouse-explainer-hero">
            <div className="flex flex-col gap-6 px-4 py-3 @3xl/warehouse-upsell:px-6 @3xl/warehouse-upsell:py-5">
                <div className="flex max-w-xl flex-col gap-2">
                    <Heading render={<h2 />} size="lg" className="m-0">
                        One warehouse for your PostHog and source data
                    </Heading>
                    <Text size="sm" variant="muted">
                        Query it with SQL in PostHog or from your own tools.
                    </Text>
                    <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
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
                            Takes a few minutes
                        </Text>
                    </div>
                </div>
                <WarehouseExplainerFlow />
            </div>
        </Card>
    )
}
