import React from 'react'
import { EventsTable } from '../events/EventsTable'
import { ActionEdit } from './ActionEdit'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { userLogic } from 'scenes/userLogic'
import { eventsTableLogic } from 'scenes/events/eventsTableLogic'

export function Action({ id }) {
    const fixedFilters = { action_id: id }

    const { push } = useActions(router)
    const { user } = useValues(userLogic)
    const { fetchEvents } = useActions(eventsTableLogic({ fixedFilters }))

    return (
        <div>
            <h1>{id ? 'Edit action' : 'New action'}</h1>
            <ActionEdit
                apiURL=""
                actionId={id}
                user={user}
                onSave={action => {
                    if (!id) {
                        push(`/action/${action.id}`)
                    }
                    fetchEvents()
                }}
            />
            <br />
            <br />

            <h2>Events</h2>
            <EventsTable fixedFilters={fixedFilters} filtersEnabled={false} />
        </div>
    )
}
