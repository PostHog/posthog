import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { eventsTableLogic } from 'scenes/LEGACY_events/eventsTableLogic'
import { EventsTable } from 'scenes/LEGACY_events/EventsTable'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: Events,
    logic: eventsTableLogic,
    paramsToProps: ({ params: { fixedFilters } }) => ({
        fixedFilters,
        key: 'EventsTable',
        sceneUrl: urls.LEGACY_events(),
    }),
}
export function Events(): JSX.Element {
    return <EventsTable pageKey={'EventsTable'} />
}
