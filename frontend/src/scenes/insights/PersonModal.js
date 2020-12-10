import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/insights/trendsLogic'
import { Modal, Button, Spin } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { LinkButton } from 'lib/components/LinkButton'

export function PersonModal({ visible, view }) {
    const { people, filters, peopleModalURL } = useValues(trendsLogic({ dashboardItemId: null, view }))
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
            width={800}
        >
            {people ? (
                <div
                    style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
                >
                    Found {people.count === 99 ? '99+' : people.count} {people.count === 1 ? 'user' : 'users'}
                    <div>
                        <LinkButton to={peopleModalURL.recordings} type="primary" target="_blank">
                            View recordings
                        </LinkButton>
                        <LinkButton to={peopleModalURL.sessions} style={{ marginLeft: 8 }} target="_blank">
                            View sessions
                        </LinkButton>
                    </div>
                </div>
            ) : (
                <p>Loading users...</p>
            )}

            <PersonsTable loading={!people?.people} people={people?.people} />
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
