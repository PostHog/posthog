import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal, Button, Spin } from 'antd'
import { PeopleTable } from 'scenes/users/PeopleTable'

export function PeopleModal({ visible, view }) {
    const { people, filters } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { setShowingPeople, loadMorePeople } = useActions(trendsLogic({ dashboardItemId: null, view }))

    const title =
        filters.shown_as === 'Stickiness'
            ? `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            : `"${people?.label}" on ${people?.day ? moment(people.day).format('ll') : '...'}`
    const closeModal = () => setShowingPeople(false)
    return (
        <Modal
            title={title}
            visible={visible}
            onOk={closeModal}
            onCancel={closeModal}
            footer={<Button onClick={closeModal}>Close</Button>}
            width={700}
        >
            {people ? (
                <p>
                    Found {people.count} {people.count === 1 ? 'user' : 'users'}
                </p>
            ) : (
                <p>Loading users...</p>
            )}

            <PeopleTable loading={!people?.people} people={people?.people} />
            <div
                style={{
                    margin: '1rem',
                    textAlign: 'center',
                }}
            >
                {people?.next && (
                    <Button type="primary" onClick={loadMorePeople}>
                        {people?.loadingMore ? <Spin /> : 'Load more people'}
                    </Button>
                )}
            </div>
        </Modal>
    )
}
