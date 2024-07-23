import { useValues } from 'kea'
import { router } from 'kea-router'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { DataWarehouseManagedSourcesTable } from 'scenes/data-warehouse/settings/DataWarehouseManagedSourcesTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { PipelineTab } from '~/types'

import { AppsManagement } from './AppsManagement'
import { Destinations } from './destinations/Destinations'
import { FrontendApps } from './FrontendApps'
import { ImportApps } from './ImportApps'
import { importAppsLogic } from './importAppsLogic'
import { Overview } from './Overview'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
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
        [PipelineTab.DataImport]: <DataWarehouseManagedSourcesTable />,
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

    return (
        <div className="pipeline-scene">
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTab))}
                tabs={Object.entries(tabToContent).map(([tab, content]) => ({
                    label: (
                        <span className="flex justify-center items-center justify-between gap-1">
                            {humanFriendlyTabName(tab as PipelineTab)}{' '}
                        </span>
                    ),
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
