import React from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { TrendPeople, parsePeopleParams, trendsLogic } from 'scenes/trends/trendsLogic'
import { DownloadOutlined } from '@ant-design/icons'
import { Modal, Button, Spin, Input, Row } from 'antd'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { ActionFilter, EntityTypes, EventPropertyFilter, FilterType, SessionsPropertyFilter } from '~/types'
import { ACTION_TYPE, EVENT_TYPE } from 'lib/constants'
import { personsModalLogic } from './personsModalLogic'
import { funnelLogic } from 'scenes/funnels/funnelLogic'

// Utility function to handle filter conversion required for deeplinking to person -> sessions
const convertToSessionFilters = (people: TrendPeople, filters: Partial<FilterType>): SessionsPropertyFilter[] => {
    if (!people?.action) {
        return []
    }
    const actions: ActionFilter[] = people.action === 'session' ? (filters.events as ActionFilter[]) : [people.action]
    return actions.map((a) => ({
        key: 'id',
        value: a.id,
        label: a.name as string,
        type: a.type === EntityTypes.ACTIONS ? ACTION_TYPE : EVENT_TYPE,
        properties: [...(a.properties || []), ...(filters.properties || [])] as EventPropertyFilter[], // combine global properties into action/event filter
    }))
}

interface Props {
    visible: boolean
    view: ViewType
    onSaveCohort: () => void
}

export function PersonModal({ visible, view, onSaveCohort }: Props): JSX.Element {
    const { people, filters, loadingMorePeople, firstLoadedPeople } = useValues(
        trendsLogic({ dashboardItemId: null, view })
    )
    const { setPersonsModalFilters } = useActions(trendsLogic({ dashboardItemId: null, view }))
    const { setShowingPeople, loadMorePeople, setFirstLoadedPeople } = useActions(
        trendsLogic({ dashboardItemId: null, view })
    )
    const { searchTerm } = useValues(personsModalLogic)
    const { setSearchTerm } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { funnelPersonsEnabled } = useValues(funnelLogic)
    const title =
        filters.shown_as === 'Stickiness'
            ? `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            : filters.display === 'ActionsBarValue' || filters.display === 'ActionsPie'
            ? `"${people?.label}"`
            : filters.insight === ViewType.FUNNELS
            ? `${people?.label}`
            : `"${people?.label}" on ${people?.day ? dayjs(people.day).format('ll') : '...'}`

    const closeModal = (): void => {
        setShowingPeople(false)
        setSearchTerm('')
    }

    return (
        <Modal
            title={<strong>{title}</strong>}
            visible={visible}
            onOk={closeModal}
            onCancel={closeModal}
            footer={
                <Row style={{ justifyContent: 'space-between' }}>
                    {featureFlags['save-cohort-on-modal'] &&
                        (view === ViewType.TRENDS || view === ViewType.STICKINESS || view === ViewType.FUNNELS) && (
                            <div>
                                <Button type="primary" onClick={onSaveCohort}>
                                    Save as cohort
                                </Button>
                            </div>
                        )}
                    <Button onClick={closeModal}>Close</Button>
                </Row>
            }
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
                        <div
                            style={{
                                display: 'flex',
                                flexDirection: 'column',
                                width: '100%',
                                alignItems: 'flex-start',
                            }}
                        >
                            <span style={{ paddingBottom: 12 }}>
                                Showing{' '}
                                <b>
                                    {people.count > 99 ? '99' : people.count} of {people.count}
                                </b>{' '}
                                persons
                            </span>
                            {funnelPersonsEnabled && (
                                <>
                                    <Input.Search
                                        allowClear
                                        enterButton
                                        placeholder="search person by email, name, or ID"
                                        style={{ width: '100%', flexGrow: 1 }}
                                        onChange={(e) => {
                                            setSearchTerm(e.target.value)
                                            if (!e.target.value) {
                                                setFirstLoadedPeople(firstLoadedPeople)
                                            }
                                        }}
                                        value={searchTerm}
                                        onSearch={(term) =>
                                            term
                                                ? setPersonsModalFilters(term, people)
                                                : setFirstLoadedPeople(firstLoadedPeople)
                                        }
                                    />
                                    <div className="text-muted text-small">
                                        You can also filter persons that have a certain property set (e.g.{' '}
                                        <code>has:email</code> or <code>has:name</code>)
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                    <div className="text-right">
                        <Button
                            icon={<DownloadOutlined />}
                            href={`/api/action/people.csv?/?${parsePeopleParams(
                                {
                                    label: people.label,
                                    action: people.action,
                                    date_from: people.day,
                                    date_to: people.day,
                                    breakdown_value: people.breakdown_value,
                                },
                                filters
                            )})}`}
                            style={{ marginBottom: '1rem' }}
                            title="Download CSV"
                        />
                    </div>
                    <PersonsTable
                        loading={!people?.people}
                        people={people.people}
                        sessionsFilters={convertToSessionFilters(people, filters)}
                        date={people?.day ? dayjs(people.day).format('YYYY-MM-DD') : undefined}
                        backTo="Insights"
                    />
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
