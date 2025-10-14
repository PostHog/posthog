import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { DataWarehouseManagedSourcesTable } from '../settings/DataWarehouseManagedSourcesTable'
import { DataWarehouseSelfManagedSourcesTable } from '../settings/DataWarehouseSelfManagedSourcesTable'

export function SourcesTab(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <SceneSection
                title="Managed data warehouse sources"
                description="PostHog can connect to external sources and automatically import data from them into the PostHog data warehouse"
            >
                <DataWarehouseManagedSourcesTable />
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title="Self-managed data warehouse sources"
                description="Connect to your own data sources, making them queryable in PostHog"
            >
                <DataWarehouseSelfManagedSourcesTable />
            </SceneSection>
        </div>
    )
}
