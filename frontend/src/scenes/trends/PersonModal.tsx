import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { Modal, Button, Spin } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { Link } from 'lib/components/Link'
import { ArrowRightOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ViewType } from 'scenes/insights/insightLogic'

interface Props {
    visible: boolean
    view: ViewType
    onSaveCohort: () => void
}

export function PersonModal({ visible, view, onSaveCohort }: Props): JSX.Element {
    const { people, filters, peopleModalURL, loadingMorePeople } = useValues(
        trendsLogic({ dashboardItemId: null, view })
    )
    const { setShowingPeople, loadMorePeople } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)

    const title =
        filters.shown_as === 'Stickiness'
            ? `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            : `"${people?.label}" on ${people?.day ? moment(people.day).format('ll') : '...'}`
    const closeModal = (): void => setShowingPeople(false)
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
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                        Found {people.count === 99 ? '99+' : people.count} {people.count === 1 ? 'user' : 'users'}
                        {featureFlags['save-cohort-on-modal'] &&
                            (view === ViewType.TRENDS || view === ViewType.STICKINESS) && (
                                <Button type="primary" onClick={onSaveCohort}>
                                    Save cohort
                                </Button>
                            )}
                    </div>
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
                        {loadingMorePeople ? <Spin /> : 'Load more people'}
                    </Button>
                )}
            </div>
        </Modal>
    )
}
