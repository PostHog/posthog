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
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            {!hideTabs && <DataManagementPageTabs tab={activeTab} />}
        </>
    )
}
