import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events/EventsTable'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: Events,
    logic: eventsTableLogic,
    paramsToProps: ({ params: { fixedFilters, pageKey } }) => ({ fixedFilters, key: pageKey, sceneUrl: urls.events() }),
}
export function Events(): JSX.Element {
    return <EventsTable />
}
