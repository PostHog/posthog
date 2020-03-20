import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal } from 'lib/components/Modal'
import { PeopleTable } from 'scenes/users/PeopleTable'

export function PeopleModal() {
    const { people, peopleCount, peopleAction, peopleDay } = useValues(trendsLogic)
    const { hidePeople } = useActions(trendsLogic)

    return (
        <Modal title={`Users for "${peopleAction?.name || '...'}" on ${peopleDay || '...'}`} onDismiss={hidePeople}>
            {people ? (
                <p>
                    Found {peopleCount} unique {peopleCount === 1 ? 'user' : 'users'}
                    {peopleCount > 100 ? '. Showing the first 100 below: ' : '.'}
                </p>
            ) : (
                <p>Loading users...</p>
            )}

            <PeopleTable loading={!people} people={people} />
        </Modal>
    )
}
