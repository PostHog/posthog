import { BindLogic } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { providersLogic } from 'scenes/messaging/providersLogic'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { pipelineDestinationsLogic } from 'scenes/pipeline/destinations/destinationsLogic'
import { HogFunctionTemplateList } from 'scenes/pipeline/hogfunctions/list/HogFunctionTemplateList'
import { SceneExport } from 'scenes/sceneTypes'

export function Providers(): JSX.Element {
    return (
        <>
            <MessagingTabs key="tabs" />
            <PageHeader caption="Configure e-mail, SMS and other messaging providers here" />
            <BindLogic logic={pipelineDestinationsLogic} props={{ type: 'email' }}>
                <DestinationsTable />
            </BindLogic>
            <div className="mt-4" />
            <h2>Add Provider</h2>
            <HogFunctionTemplateList defaultFilters={{}} type="email" />
        </>
    )
}
export const scene: SceneExport = {
    component: Providers,
    logic: providersLogic,
}
