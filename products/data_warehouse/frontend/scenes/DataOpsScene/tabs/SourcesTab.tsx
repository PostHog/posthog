import { useValues } from 'kea'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { DirectConnectSourcesTable } from 'products/data_warehouse/frontend/shared/components/DirectConnectSourcesTable'
import { ManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/ManagedSourcesTable'
import { SelfManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/SelfManagedSourcesTable'
import { sourceManagementLogic } from 'products/data_warehouse/frontend/shared/logics/sourceManagementLogic'

export function SourcesTab(): JSX.Element {
    const { hasSelfManagedTables } = useValues(sourceManagementLogic)

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
                title="Direct connect sources"
                description="Query these sources live from PostHog. Your data stays where it is, nothing gets imported"
            >
                <DirectConnectSourcesTable />
            </SceneSection>
            {hasSelfManagedTables && (
                <>
                    <SceneDivider />
                    <SceneSection
                        title="Self-managed data warehouse sources"
                        description="Tables that PostHog reads in place from your own bucket"
                    >
                        <SelfManagedSourcesTable />
                    </SceneSection>
                </>
            )}
        </div>
    )
}
