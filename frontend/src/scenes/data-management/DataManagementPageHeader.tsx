import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'

export function DataManagementPageHeader({
    activeTab,
    hideTabs,
}: {
    activeTab: DataManagementTab
    hideTabs?: boolean
}): JSX.Element {
    return (
        <>
            <PageHeader
                title="Events & Actions"
                caption="See events being sent to this project and manage custom actions. Event history is limited to the last twelve months."
                tabbedPage
            />
            {!hideTabs && <DataManagementPageTabs tab={activeTab} />}
        </>
    )
}
