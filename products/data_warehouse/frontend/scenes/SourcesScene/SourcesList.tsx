import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { urls } from 'scenes/urls'

import { SceneDivider } from '~/layout/scenes/components/SceneDivider'
import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { DirectConnectSourcesTable } from 'products/data_warehouse/frontend/shared/components/DirectConnectSourcesTable'
import { ManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/ManagedSourcesTable'
import { SelfManagedSourcesTable } from 'products/data_warehouse/frontend/shared/components/SelfManagedSourcesTable'

export function SourcesList(): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <SceneSection
                title="Managed data warehouse sources"
                description="PostHog can connect to external sources and automatically import data from them into the PostHog data warehouse"
            >
                <ManagedSourcesTable />
            </SceneSection>
            <SceneDivider />

            <FlaggedFeature flag="cdp-hog-sources">
                <>
                    <SceneSection
                        title={
                            <span className="flex items-center gap-2">
                                Event sources
                                <LemonTag type="primary" size="small">
                                    Experimental
                                </LemonTag>
                            </span>
                        }
                        description="PostHog can expose a webhook that you can configure however you need to receive data from a 3rd party with no in-between service necessary"
                        actions={
                            <LemonButton
                                type="primary"
                                size="small"
                                icon={<IconPlusSmall />}
                                to={urls.hogFunctionNew('template-source-webhook')}
                                data-attr="new-event-source"
                            >
                                New event source
                            </LemonButton>
                        }
                    >
                        <HogFunctionList logicKey="data-pipelines-hog-functions-source-webhook" type="source_webhook" />
                    </SceneSection>
                    <SceneDivider />
                </>
            </FlaggedFeature>

            <SceneSection
                title="Direct connect sources"
                description="Query these sources live from PostHog. Your data stays where it is, nothing gets imported"
            >
                <DirectConnectSourcesTable />
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
