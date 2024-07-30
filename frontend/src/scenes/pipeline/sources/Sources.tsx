import { PageHeader } from 'lib/components/PageHeader'
import { DatabaseTableList } from 'scenes/data-management/database/DatabaseTableList'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseSelfManagedSourcesTable'

import { PipelineStage } from '~/types'

import { NewButton } from '../NewButton'

export function Sources(): JSX.Element {
    return (
        <>
            <PageHeader buttons={<NewButton stage={PipelineStage.Source} />} />

            <div className="space-y-4">
                <div>
                    <h2>Managed sources</h2>
                    <p>
                        PostHog can connect to external sources and automatically import data from them into the PostHog
                        data warehouse
                    </p>
                    <DataWarehouseManagedSourcesTable />
                </div>
                <div>
                    <h2>Self managed sources</h2>
                    <p>Connect to your own data sources, making them queryable in PostHog</p>
                    <DataWarehouseSelfManagedSourcesTable />
                </div>
                <div>
                    <h2>All tables</h2>
                    <p>Below are all the tables and schemas you are able to query</p>
                    <DatabaseTableList />
                </div>
            </div>
        </>
    )
}
