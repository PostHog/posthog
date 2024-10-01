import { useValues } from 'kea'
import { router } from 'kea-router'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ConcreteLemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityScope, PipelineTab } from '~/types'

import { AppsManagement } from './AppsManagement'
import { Destinations } from './destinations/Destinations'
import { FrontendApps } from './FrontendApps'
import { ImportApps } from './ImportApps'
import { importAppsLogic } from './importAppsLogic'
import { Overview } from './Overview'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { humanFriendlyTabName, pipelineLogic } from './pipelineLogic'
import { Sources } from './sources/Sources'
import { Transformations } from './Transformations'

export function Pipeline(): JSX.Element {
    const { canGloballyManagePlugins } = useValues(pipelineAccessLogic)
    const { currentTab } = useValues(pipelineLogic)
    const { hasEnabledImportApps } = useValues(importAppsLogic)

    const tabs: Pick<ConcreteLemonTab<PipelineTab>, 'key' | 'content'>[] = [
        { key: PipelineTab.Overview, content: <Overview /> },
        { key: PipelineTab.Sources, content: <Sources /> },
        { key: PipelineTab.Transformations, content: <Transformations /> },
        { key: PipelineTab.Destinations, content: <Destinations /> },
        { key: PipelineTab.SiteApps, content: <FrontendApps /> },
    ]

    // Import apps are deprecated, we only show the tab if there are some still enabled
    if (hasEnabledImportApps) {
        tabs.push({ key: PipelineTab.ImportApps, content: <ImportApps /> })
    }
    if (canGloballyManagePlugins) {
        tabs.push({ key: PipelineTab.AppsManagement, content: <AppsManagement /> })
    }

    tabs.push({
        key: PipelineTab.History,
        content: <ActivityLog scope={`${ActivityScope.HOG_FUNCTION},${ActivityScope.PLUGIN}`} />,
    })

    return (
        <div className="pipeline-scene">
            <LemonTabs
                activeKey={currentTab}
                onChange={(tab) => router.actions.push(urls.pipeline(tab as PipelineTab))}
                tabs={tabs.map((tab) => ({
                    ...tab,
                    label: humanFriendlyTabName(tab.key),
                }))}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Pipeline,
    logic: pipelineLogic,
}
