import React from 'react'
import { EventsTable } from './EventsTable'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'

export const logic = eventsTableLogic

export function Events(props) {
    return <EventsTable {...props} />
}
