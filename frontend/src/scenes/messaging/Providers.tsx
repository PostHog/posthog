import { PageHeader } from 'lib/components/PageHeader'
import { MessagingTabs } from 'scenes/messaging/MessagingTabs'
import { providersLogic } from 'scenes/messaging/providersLogic'
import { DestinationsTable } from 'scenes/pipeline/destinations/Destinations'
import { LinkedHogFunctions } from 'scenes/pipeline/hogfunctions/list/LinkedHogFunctions'
import { SceneExport } from 'scenes/sceneTypes'

import { HogFunctionFiltersType } from '~/types'

export function Providers(): JSX.Element {
    const filters: HogFunctionFiltersType = {
        actions: [
            // {
            //     id: `${action?.id}`,
            //     name: action?.name,
            //     type: 'actions',
            // },
        ],
    }

    return (
        <>
            <MessagingTabs key="tabs" />
            <PageHeader
                caption="Configure e-mail, SMS and other messaging providers here"
                // buttons={<NewButton stage={PipelineStage.Destination} />}
            />
            <DestinationsTable />
            <div className="mt-4" />
            <h2>Providers</h2>
            <LinkedHogFunctions filters={filters} />
        </>
    )
}
export const scene: SceneExport = {
    component: Providers,
    logic: providersLogic,
}
