import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { SceneExport } from 'scenes/sceneTypes'

export function History(): JSX.Element {
    return (
        <div data-attr="database-scene">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.History} />
            <ActivityLog
                scope={ActivityScope.DATA_MANAGEMENT}
                caption={
                    'Only actions taken in the UI are captured in History. Automatic creation of definitions by ingestion is not shown here.'
                }
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: History,
}
