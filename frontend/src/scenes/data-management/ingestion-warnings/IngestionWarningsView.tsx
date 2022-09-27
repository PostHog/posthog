import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { PageHeader } from 'lib/components/PageHeader'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { ingestionWarningsLogic } from './ingestionWarningsLogic'

export const scene: SceneExport = {
    component: IngestionWarningsView,
    logic: ingestionWarningsLogic,
}

export function IngestionWarningsView(): JSX.Element {
    return (
        <div data-attr="manage-events-table">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.IngestionWarnings} />
        </div>
    )
}
