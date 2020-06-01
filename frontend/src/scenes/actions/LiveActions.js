import React from 'react'

import { eventsTableLogic } from 'scenes/events/eventsTableLogic'
import { EventsTable } from 'scenes/events/EventsTable'

export function LiveActions(props) {
    return (
        <EventsTable
            {...props}
            isLiveActions={true}
            logic={eventsTableLogic({ fixedFilters: undefined, apiUrl: 'api/event/actions/', live: true })}
        />
    )
}
