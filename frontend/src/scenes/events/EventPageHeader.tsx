import { PageHeader } from 'lib/components/PageHeader'
import React from 'react'
import { EventsTab, EventsTabs } from '.'

export function EventPageHeader({ activeTab, hideTabs }: { activeTab: EventsTab; hideTabs?: boolean }): JSX.Element {
    return (
        <>
            <PageHeader
                title="Events &amp; actions"
                caption="See events being sent to this project and manage custom actions."
                tabbedPage
            />
            {!hideTabs && <EventsTabs tab={activeTab} />}
        </>
    )
}
