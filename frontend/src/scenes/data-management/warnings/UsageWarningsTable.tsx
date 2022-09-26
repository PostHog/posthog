import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { DataManagementPageTabs, DataManagementTab } from 'scenes/data-management/DataManagementPageTabs'
import { PageHeader } from 'lib/components/PageHeader'
import { EventsTable } from 'scenes/events'
import { urls } from 'scenes/urls'
import { useValues } from 'kea'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { NotFound } from 'lib/components/NotFound'
import { usageWarningsTableLogic } from './UsageWarningsTableLogic'

export const scene: SceneExport = {
    component: UsageWarningsTable,
    logic: usageWarningsTableLogic,
}

export function UsageWarningsTable(): JSX.Element {
    const { person, personLoading } = useValues(usageWarningsTableLogic)
    if (!person) {
        return personLoading ? <SpinnerOverlay /> : <NotFound object="Person" />
    }

    return (
        <div data-attr="manage-events-table">
            <PageHeader
                title="Data Management"
                caption="Use data management to organize events that come into PostHog. Reduce noise, clarify usage, and help collaborators get the most value from your data."
                tabbedPage
            />
            <DataManagementPageTabs tab={DataManagementTab.UsageWarnings} />
            <EventsTable
                pageKey={'WarningsTable'}
                fixedFilters={{ person_id: person.id }}
                showPersonColumn={false}
                showCustomizeColumns={false}
                showExport={false}
                showEventFilter={false}
                showPropertyFilter={true}
                // showRowExpanders={false}
                showActionsButton={false}
                linkPropertiesToFilters={false}
                startingColumns={['description', 'event_uuid']} // TODO: need to use something else, note that webperformance.tsx uses it and maybe shouldn't? as that breaks live-events for that team
                data-attr="warnings-events-table"
                sceneUrl={urls.usageWarnings()}
            />
        </div>
    )
}
