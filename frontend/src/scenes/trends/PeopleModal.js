import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal } from 'lib/components/Modal'
import { PeopleTable } from 'scenes/users/PeopleTable'

export function PeopleModal() {
    const { people, filters } = useValues(trendsLogic({ id: null }))
    const { setShowingPeople } = useActions(trendsLogic({ dashboardItemId: null }))

    const title =
        filters.shown_as === 'Stickiness'
            ? `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            : `"${people?.label}" on ${people?.day ? moment(people.day).format('ll') : '...'}`

    return (
        <Modal title={title} onDismiss={() => setShowingPeople(false)}>
            {people ? (
                <p>
                    Found {people.count} {people.count === 1 ? 'user' : 'users'}
                    {people.count > 100 ? '. Showing the first 100 below.' : ''}
                </p>
            ) : (
                <p>Loading users...</p>
            )}

            <PeopleTable loading={!people?.people} people={people?.people} />
        </Modal>
    )
}
