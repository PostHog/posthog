import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal } from 'lib/components/Modal'
import { PeopleTable } from 'scenes/users/PeopleTable'

export function PeopleModal() {
    const { people, peopleCount, peopleAction, peopleDay, filters } = useValues(trendsLogic)
    const { hidePeople } = useActions(trendsLogic)

    const title =
        filters.shown_as === 'Stickiness'
            ? `"${peopleAction?.name || '...'}" stickiness ${peopleDay} day${peopleDay === 1 ? '' : 's'}`
            : `"${peopleAction?.name || '...'}" on ${peopleDay ? moment(peopleDay).format('ll') : '...'}`

    return (
        <Modal title={title} onDismiss={hidePeople}>
            {people ? (
                <p>
                    Found {peopleCount} {peopleCount === 1 ? 'user' : 'users'}
                    {peopleCount > 100 ? '. Showing the first 100 below.' : ''}
                </p>
            ) : (
                <p>Loading users...</p>
            )}

            <PeopleTable loading={!people} people={people} />
        </Modal>
    )
}
