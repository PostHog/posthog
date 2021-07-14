import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { TrendPeople, parsePeopleParams } from 'scenes/trends/trendsLogic'
import { DownloadOutlined, UsergroupAddOutlined } from '@ant-design/icons'
import { Modal, Button, Spin, Input, Row, Col, Skeleton } from 'antd'
import { deepLinkToPersonSessions } from 'scenes/persons/PersonsTable'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ViewType } from 'scenes/insights/insightLogic'
import { ActionFilter, EntityTypes, EventPropertyFilter, FilterType, SessionsPropertyFilter } from '~/types'
import { ACTION_TYPE, EVENT_TYPE, FEATURE_FLAGS } from 'lib/constants'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { Link } from 'lib/components/Link'
import './PersonModal.scss'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ExpandIcon, ExpandIconProps } from 'lib/components/ExpandIcon'
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
    filters: Partial<FilterType>
    onSaveCohort: () => void
}

export function PersonModal({ visible, view, filters, onSaveCohort }: Props): JSX.Element {
    const { people, loadingMorePeople, firstLoadedPeople, searchTerm, peopleLoading } = useValues(personsModalLogic)
    const {
        setShowingPeople,
        loadMorePeople,
        setFirstLoadedPeople,
        setPersonsModalFilters,
        setSearchTerm,
    } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
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
                <Row style={{ justifyContent: 'space-between', alignItems: 'center', padding: '6px 0px' }}>
                    <Row style={{ alignItems: 'center' }}>
                        {featureFlags['save-cohort-on-modal'] &&
                            (view === ViewType.TRENDS || view === ViewType.STICKINESS || view === ViewType.FUNNELS) && (
                                <div style={{ paddingRight: 8 }}>
                                    <Button onClick={onSaveCohort}>
                                        <UsergroupAddOutlined />
                                        Save as cohort
                                    </Button>
                                </div>
                            )}
                        {!peopleLoading && people && (
                            <>
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
                                    title="Download CSV"
                                >
                                    Download CSV
                                </Button>
                            </>
                        )}
                    </Row>
                    <Button onClick={closeModal}>Close</Button>
                </Row>
            }
            width={600}
            bodyStyle={{ padding: 0, maxHeight: 500, overflowY: 'scroll' }}
            className="person-modal"
        >
            {peopleLoading && (
                <div style={{ padding: 16 }}>
                    <Skeleton active />
                </div>
            )}
            {!peopleLoading && people && (
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
                                padding: '0px 16px',
                            }}
                        >
                            {featureFlags[FEATURE_FLAGS.PERSONS_MODAL_SEARCH] && (
                                <Input.Search
                                    allowClear
                                    enterButton
                                    placeholder="Search person by email, name, or ID"
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
                                            ? setPersonsModalFilters(term, people, filters)
                                            : setFirstLoadedPeople(firstLoadedPeople)
                                    }
                                />
                            )}
                            <span style={{ paddingTop: 9 }}>
                                Showing{' '}
                                <b>
                                    {people.count > 99 ? '99' : people.count} of {people.count}
                                </b>{' '}
                                persons
                            </span>
                        </div>
                    </div>
                    <Col style={{ background: '#FAFAFA' }}>
                        {people?.people.map((person) => (
                            <div key={person.id}>
                                <PersonRow person={person} people={people} filters={filters} />
                            </div>
                        ))}
                    </Col>
                    <div
                        style={{
                            margin: '1rem',
                            textAlign: 'center',
                        }}
                    >
                        {people?.next && (
                            <Button type="primary" style={{ color: 'white' }} onClick={loadMorePeople}>
                                {loadingMorePeople ? <Spin /> : 'Load more people'}
                            </Button>
                        )}
                    </div>
                </>
            )}
        </Modal>
    )
}

interface PersonRowProps {
    person: any
    people: any
    filters: any
}

export function PersonRow({ person, people, filters }: PersonRowProps): JSX.Element {
    const [showProperties, setShowProperties] = useState(false)
    const expandProps = {
        record: '',
        onExpand: () => setShowProperties(!showProperties),
        expanded: showProperties,
        expandable: Object.keys(person.properties).length > 0,
        prefixCls: 'ant-table',
    } as ExpandIconProps

    return (
        <Col
            key={person.id}
            style={{
                alignItems: 'center',
                padding: '14px 8px',
                borderBottom: '1px solid #D9D9D9',
            }}
        >
            <Row style={{ justifyContent: 'space-between' }}>
                <Row>
                    <ExpandIcon {...expandProps}>{undefined}</ExpandIcon>
                    <Col>
                        <span className="text-default">
                            <strong>{person.properties.email}</strong>
                        </span>
                        <div className="text-small text-muted-alt">
                            <CopyToClipboardInline
                                explicitValue={person.distinct_ids[0]}
                                tooltipMessage=""
                                iconStyle={{ color: 'var(--primary)' }}
                                iconPosition="end"
                            >
                                {midEllipsis(person.distinct_ids[0], 32)}
                            </CopyToClipboardInline>
                        </div>
                    </Col>
                </Row>
                <Button>
                    <Link
                        to={deepLinkToPersonSessions(
                            person,
                            convertToSessionFilters(people, filters),
                            people?.day ? dayjs(people.day).format('YYYY-MM-DD') : '',
                            'Insights'
                        )}
                    >
                        View details
                    </Link>
                </Button>
            </Row>
            {showProperties && (
                <Row className="person-modal-properties" style={{ paddingTop: 16 }}>
                    <PropertiesTable properties={person.properties} />
                </Row>
            )}
        </Col>
    )
}
