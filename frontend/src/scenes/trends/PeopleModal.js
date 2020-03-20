import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal } from 'lib/components/Modal'
import { PeopleTable } from 'scenes/users/PeopleTable'

export function PeopleModal() {
    const {
        people,
        peopleMeta: { action, day, count },
    } = useValues(trendsLogic)
    const { hidePeople } = useActions(trendsLogic)

    return (
        <Modal title={`Users for "${action?.name}" on ${day}`} onDismiss={hidePeople}>
            {people ? (
                <p>
                    Found {count} unique {count === 1 ? 'user' : 'users'}
                    {count > 100 ? '. Showing the first 100 below: ' : '.'}
                </p>
            ) : (
                <p>Loading users...</p>
            )}

            <PeopleTable loading={!people} people={people} />
        </Modal>
    )
}
