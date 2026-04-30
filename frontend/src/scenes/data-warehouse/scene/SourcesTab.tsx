import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { ManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/ManagedSourcesTable'
import { SelfManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/SelfManagedSourcesTable'

export function SourcesTab(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <SceneSection
                title="Managed data warehouse sources"
                description="PostHog can connect to external sources and automatically import data from them into the PostHog data warehouse"
            >
                <ManagedSourcesTable />
            </SceneSection>
            <SceneDivider />
            <SceneSection
                title="Self-managed data warehouse sources"
                description="Connect to your own data sources, making them queryable in PostHog"
            >
                <SelfManagedSourcesTable />
            </SceneSection>
        </div>
    )
}
