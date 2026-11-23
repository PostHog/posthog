import { useValues } from 'kea'

import { Heading, ItemGroup } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { WarehouseGettingStartedStep } from './WarehouseGettingStartedStep'
import { warehouseHomeLogic } from './warehouseHomeLogic'

// pinned: the data-attr values in this file feed autocapture and dashboards, so renaming them breaks both.

export function WarehouseGettingStarted(): JSX.Element {
    const { sourceStep, viewStep } = useValues(warehouseHomeLogic)

    return (
        <section aria-labelledby="warehouse-getting-started" className="flex flex-col gap-2">
            <Heading render={<h2 id="warehouse-getting-started" />} size="base" className="m-0">
                Getting started
            </Heading>
            <ItemGroup className="gap-2">
                <WarehouseGettingStartedStep
                    step="connect_source"
                    index={1}
                    state={sourceStep}
                    title="Connect a source"
                    description="Import data from tools like Stripe, Hubspot or Postgres."
                    actions={[
                        {
                            label: 'Add source',
                            to: urls.dataWarehouseSourceNew(),
                            dataAttr: 'warehouse-home-connect-source',
                        },
                    ]}
                />
                <WarehouseGettingStartedStep
                    step="create_view"
                    index={2}
                    state={viewStep}
                    title="Create a view"
                    description="Write SQL that joins and cleans your data into a view you can reuse."
                    actions={[
                        { label: 'Open SQL editor', to: urls.sqlEditor(), dataAttr: 'warehouse-home-create-view' },
                    ]}
                />
            </ItemGroup>
        </section>
    )
}
