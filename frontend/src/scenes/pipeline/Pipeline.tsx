import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTabs } from '~/types'

import { AppsManagement } from './AppsManagement'
import { Destinations } from './Destinations'
import { NewButton } from './NewButton'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { currentTab } = useValues(pipelineLogic)

    const tab_to_content: Record<PipelineTabs, JSX.Element> = {
        [PipelineTabs.Filters]: <div>Coming soon</div>,
        [PipelineTabs.Transformations]: <Transformations />,
        [PipelineTabs.Destinations]: <Destinations />,
        [PipelineTabs.AppsManagement]: <AppsManagement />,
    }

    return (
        <div className="pipeline-scene">
            <PageHeader
                title="Pipeline"
                caption="Add filters or transformations to the events sent to PostHog or export them to other tools."
                buttons={<NewButton tab={currentTab} />}
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTabs))}
                tabs={Object.values(PipelineTabs).map((tab) => ({
                    label: humanFriendlyTabName(tab),
                    key: tab,
                    content: tab_to_content[tab],
                }))}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
