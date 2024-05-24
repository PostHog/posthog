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
import { importAppsLogic } from './importAppsLogic'
import { NewButton } from './NewButton'
import { Overview } from './Overview'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { PIPELINE_TAB_TO_NODE_STAGE } from './PipelineNode'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { canGloballyManagePlugins } = useValues(pipelineAccessLogic)
    const { currentTab } = useValues(pipelineLogic)
    const { hasEnabledImportApps } = useValues(importAppsLogic)

    let tabToContent: Partial<Record<PipelineTab, JSX.Element>> = {
        [PipelineTab.Overview]: <Overview />,
        [PipelineTab.Transformations]: <Transformations />,
        [PipelineTab.Destinations]: <Destinations />,
        [PipelineTab.SiteApps]: <FrontendApps />,
    }
    // Import apps are deprecated, we only show the tab if there are some still enabled
    if (hasEnabledImportApps) {
        tabToContent = {
            ...tabToContent,
            [PipelineTab.ImportApps]: <ImportApps />,
        }
    }
    if (canGloballyManagePlugins) {
        tabToContent = {
            ...tabToContent,
            [PipelineTab.AppsManagement]: <AppsManagement />,
        }
    }

    const maybeKind = PIPELINE_TAB_TO_NODE_STAGE[currentTab]

    return (
        <div className="pipeline-scene">
            <PageHeader
                caption="Add transformations to the events sent to PostHog or export them to other tools."
                buttons={maybeKind ? <NewButton stage={maybeKind} /> : undefined}
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
