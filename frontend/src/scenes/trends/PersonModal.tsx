import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { DownloadOutlined } from '@ant-design/icons'
import { Modal, Button, Spin, Input } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { toParams } from 'lib/utils'
import { PersonType } from '~/types'
import Fuse from 'fuse.js'

interface Props {
    visible: boolean
    view: ViewType
    onSaveCohort: () => void
}

const searchPersons = (sources: PersonType[], search: string): PersonType[] => {
    return new Fuse(sources, {
        keys: ['name', 'email', 'id'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export function PersonModal({ visible, view, onSaveCohort }: Props): JSX.Element {
    const { people, filters, loadingMorePeople, firstLoadedPeople } = useValues(
        trendsLogic({ dashboardItemId: null, view })
    )
    const { setPersonsModalFilters } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { setShowingPeople, loadMorePeople, setPeople } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { featureFlags } = useValues(featureFlagLogic)
    const [searchTerm, setSearchTerm] = useState('')
    const title =
        filters.shown_as === 'Stickiness'
            ? `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            : filters.display === 'ActionsBarValue' || filters.display === 'ActionsPie'
            ? `"${people?.label}"`
            : `"${people?.label}" on ${people?.day ? dayjs(people.day).format('ll') : '...'}`
    const closeModal = (): void => {
        setShowingPeople(false)
    }

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
                <>
                    <div
                        style={{
                            marginBottom: 16,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                        }}
                    >
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                            <span>
                                Showing{' '}
                                <b>
                                    {people.count > 99 ? '99' : people.count} of {people.count}
                                </b>{' '}
                                persons
                            </span>
                            <Input.Search
                                allowClear
                                enterButton
                                style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                                onChange={(e) => {
                                    setSearchTerm(e.target.value)
                                    if (!e.target.value) {
                                        setPeople(
                                            firstLoadedPeople?.people,
                                            people.count,
                                            people.action,
                                            people.label,
                                            people.day,
                                            people.breakdown_value,
                                            people.next
                                        )
                                    }
                                }}
                                value={searchTerm}
                                onSearch={() => {
                                    if (!searchTerm) {
                                        const { count, action, label, day, breakdown_value, next } = people
                                        setPeople(
                                            firstLoadedPeople?.people,
                                            count,
                                            action,
                                            label,
                                            day,
                                            breakdown_value,
                                            next
                                        )
                                    } else if (searchTerm.includes('has:')) {
                                        setPersonsModalFilters(searchTerm, people)
                                    } else {
                                        const ppl = searchPersons(people.people, searchTerm)
                                        setPeople(ppl, people.count, people.action, people.label, people.day)
                                    }
                                }}
                            />
                            {featureFlags['save-cohort-on-modal'] &&
                                (view === ViewType.TRENDS || view === ViewType.STICKINESS) && (
                                    <div>
                                        <Button type="primary" onClick={onSaveCohort}>
                                            Save cohort
                                        </Button>
                                    </div>
                                )}
                        </div>
                    </div>
                    <div className="text-right">
                        <Button
                            icon={<DownloadOutlined />}
                            href={`/api/action/people.csv?/?${toParams({
                                ...(filters || {}),
                                entity_id: people.action.id,
                                entity_type: people.action.type,
                                date_from: people.day,
                                date_to: people.day,
                                label: people.label,
                            })}`}
                            style={{ marginBottom: '1rem' }}
                            title="Download CSV"
                        />
                    </div>
                    <PersonsTable loading={!people?.people} people={people.people} />
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
                </>
            ) : (
                <p>Loading users...</p>
            )}
        </Modal>
    )
}
