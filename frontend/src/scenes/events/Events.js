import React from 'react'
import { EventsTable } from './EventsTable'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { hot } from 'react-hot-loader/root'

export const logic = eventsTableLogic

export const Events = hot(_Events)
function _Events(props) {
    return <EventsTable {...props} logic={eventsTableLogic({ fixedFilters: props.fixedFilters })} />
}
