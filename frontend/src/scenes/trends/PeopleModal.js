import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Loading } from 'lib/utils'
import { Modal } from 'lib/components/Modal'

export function PeopleModal() {
    const {
        people,
        peopleMeta: { action, day, count },
    } = useValues(trendsLogic)
    const { hidePeople } = useActions(trendsLogic)

    return (
        <Modal title={`People for "${action?.name}" on ${day}`} onDismiss={hidePeople}>
            {people ? (
                <div>
                    <div style={{ marginBottom: 10 }}>
                        Found {count} unique {count === 1 ? 'person' : 'people'}
                        {count > 100 ? '. Showing the first 100 below: ' : ':'}
                    </div>

                    {people.map(person => (
                        <div key={person.id}>
                            <a href="#">{person.name}</a>
                        </div>
                    ))}
                </div>
            ) : (
                <Loading />
            )}
        </Modal>
    )
}
