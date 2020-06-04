import React from 'react'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { hot } from 'react-hot-loader/root'
import { EventsTable } from 'scenes/events/EventsTable'

export const LiveActions = hot(_LiveActions)
function _LiveActions(props) {
    return (
        <EventsTable
            {...props}
            isLiveActions={true}
            logic={eventsTableLogic({ fixedFilters: undefined, apiUrl: 'api/event/actions/', live: true })}
        />
    )
}
