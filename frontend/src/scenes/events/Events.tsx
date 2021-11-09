import React from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events/EventsTable'

export const scene: SceneExport = {
    component: Events,
    logic: eventsTableLogic,
    paramsToProps: ({ params: { fixedFilters, pageKey } }) => ({ fixedFilters, key: pageKey }),
}
export function Events(): JSX.Element {
    return <EventsTable />
}
