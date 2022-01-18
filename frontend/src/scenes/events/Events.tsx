import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events/EventsTable'
import { urls } from 'scenes/urls'
import { EventPageHeader } from './EventPageHeader'
import { EventsTab } from '.'

export const scene: SceneExport = {
    component: Events,
    logic: eventsTableLogic,
    paramsToProps: ({ params: { fixedFilters } }) => ({ fixedFilters, key: 'EventsTable', sceneUrl: urls.events() }),
}
export function Events(): JSX.Element {
    return (
        <>
            <EventPageHeader activeTab={EventsTab.Events} />
            <EventsTable pageKey={'EventsTable'} />
        </>
    )
}
