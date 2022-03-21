import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events/EventsTable'
import { urls } from 'scenes/urls'
import { PageHeader } from 'lib/components/PageHeader'

export const scene: SceneExport = {
    component: Events,
    logic: eventsTableLogic,
    paramsToProps: ({ params: { fixedFilters } }) => ({ fixedFilters, key: 'EventsTable', sceneUrl: urls.events() }),
}

export function Events(): JSX.Element {
    return (
        <>
            <PageHeader title="Live events" caption="Event history is limited to the last twelve months." />
            <EventsTable pageKey={'EventsTable'} />
        </>
    )
}
