import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { AppsManagement } from './AppsManagement'
import { Destinations } from './Destinations'
import { NewButton } from './NewButton'
import { Overview } from './Overview'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { currentTab } = useValues(pipelineLogic)

    const tabToContent: Record<PipelineTab, JSX.Element> = {
        [PipelineTab.Overview]: <Overview />,
        [PipelineTab.Transformations]: <Transformations />,
        [PipelineTab.Destinations]: <Destinations />,
        [PipelineTab.AppsManagement]: <AppsManagement />,
    }

    const maybeKind = PIPELINE_TAB_TO_NODE_STAGE[currentTab]

    return (
        <div className="pipeline-scene">
            <PageHeader
                caption="Add filters or transformations to the events sent to PostHog or export them to other tools."
                buttons={maybeKind ? <NewButton stage={maybeKind} /> : undefined}
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTab))}
                tabs={Object.values(PipelineTab).map((tab) => ({
                    // TODO: Hide admin management based on `canGloballyManagePlugins` permission
                    label: humanFriendlyTabName(tab),
                    key: tab,
                    content: tabToContent[tab],
                }))}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
