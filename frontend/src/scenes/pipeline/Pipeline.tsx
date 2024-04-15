import { useValues } from 'kea'
import { router } from 'kea-router'
import { PageHeader } from 'lib/components/PageHeader'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { AppsManagement } from './AppsManagement'
import { Destinations } from './Destinations'
import { FrontendApps } from './FrontendApps'
import { ImportApps } from './ImportApps'
import { NewButton } from './NewButton'
import { Overview } from './Overview'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { currentTab, canEnableNewDestinations, canGloballyManagePlugins } = useValues(pipelineLogic)

    let tabToContent: Partial<Record<PipelineTab, JSX.Element>> = {
        [PipelineTab.Overview]: <Overview />,
        [PipelineTab.Transformations]: <Transformations />,
        [PipelineTab.Destinations]: <Destinations />,
        [PipelineTab.SiteApps]: <FrontendApps />,
        [PipelineTab.ImportApps]: <ImportApps />, // TODO: only show if some enabled
    }
    if (canGloballyManagePlugins) {
        tabToContent = {
            ...tabToContent,
            [PipelineTab.AppsManagement]: <AppsManagement />,
        }
    }

    const maybeKind = PIPELINE_TAB_TO_NODE_STAGE[currentTab]
    const showNewButton = maybeKind && (currentTab !== PipelineTab.Destinations || canEnableNewDestinations)

    return (
        <div className="pipeline-scene">
            <PageHeader
                caption="Add transformations to the events sent to PostHog or export them to other tools."
                buttons={showNewButton ? <NewButton stage={maybeKind} /> : undefined}
            />
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTab))}
                tabs={Object.entries(tabToContent).map(([tab, content]) => ({
                    label: humanFriendlyTabName(tab as PipelineTab),
                    key: tab,
                    content: content,
                }))}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
