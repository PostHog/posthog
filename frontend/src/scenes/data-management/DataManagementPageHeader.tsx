import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'

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
                title={
                    <div className="flex-center">
                        Data Management
                        <LemonTag type="warning" style={{ marginLeft: 6, lineHeight: '1.4em' }}>
                            BETA
                        </LemonTag>
                    </div>
                }
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            {!hideTabs && <DataManagementPageTabs tab={activeTab} />}
        </>
    )
}
