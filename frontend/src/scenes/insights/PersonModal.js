import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/insights/trendsLogic'
import { Modal, Button, Spin } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { Link } from 'lib/components/Link'
import { ArrowRightOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export function PersonModal({ visible, view }) {
    const { people, filters, peopleModalURL } = useValues(trendsLogic({ dashboardItemId: null, view }))
    const { setShowingPeople, loadMorePeople } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)

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
                    {featureFlags['filter_by_session_props_link'] ? (
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
                            <Link
                                to={peopleModalURL.sessions}
                                style={{ marginLeft: 8 }}
                                data-attr="persons-modal-sessions"
                            >
                                <ClockCircleOutlined /> View related sessions <ArrowRightOutlined />
                            </Link>
                            <Link to={peopleModalURL.recordings} type="primary" data-attr="persons-modal-recordings">
                                View related recordings <ArrowRightOutlined />
                            </Link>
                        </div>
                    ) : null}
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
