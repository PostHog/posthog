import React, { useMemo, useState } from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { TrendPeople, parsePeopleParams } from 'scenes/trends/trendsLogic'
import { DownloadOutlined, UsergroupAddOutlined, ReloadOutlined } from '@ant-design/icons'
import { Modal, Button, Spin, Input, Row, Col, Skeleton } from 'antd'
import { deepLinkToPersonSessions } from 'scenes/persons/PersonsTable'
import { ActionFilter, EntityTypes, EventPropertyFilter, FilterType, SessionsPropertyFilter, ViewType } from '~/types'
import { ACTION_TYPE, EVENT_TYPE } from 'lib/constants'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis } from 'lib/utils'
import { Link } from 'lib/components/Link'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ExpandIcon, ExpandIconProps } from 'lib/components/ExpandIcon'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { DateDisplay } from 'lib/components/DateDisplay'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

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
    const {
        people,
        loadingMorePeople,
        firstLoadedPeople,
        searchTerm,
        isInitialLoad,
        clickhouseFeaturesEnabled,
    } = useValues(personsModalLogic)
    const {
        reloadPeople,
        hidePeople,
        loadMorePeople,
        setFirstLoadedPeople,
        setPersonsModalFilters,
        setSearchTerm,
    } = useActions(personsModalLogic)
    const { preflight } = useValues(preflightLogic)
    const title = useMemo(
        () =>
            isInitialLoad ? (
                'Loading persons list...'
            ) : filters.shown_as === 'Stickiness' ? (
                `"${people?.label}" stickiness ${people?.day} day${people?.day === 1 ? '' : 's'}`
            ) : filters.display === 'ActionsBarValue' || filters.display === 'ActionsPie' ? (
                `"${people?.label}"`
            ) : filters.insight === ViewType.FUNNELS ? (
                <>
                    Persons who {(people?.funnelStep ?? 0) >= 0 ? 'completed' : 'dropped off at'} step #
                    {Math.abs(people?.funnelStep ?? 0)} - <PropertyKeyInfo value={people?.label || ''} disablePopover />{' '}
                    {people?.breakdown_value !== undefined &&
                        `- ${people.breakdown_value ? people.breakdown_value : 'None'}`}
                </>
            ) : (
                <>
                    <PropertyKeyInfo value={people?.label || ''} disablePopover /> on{' '}
                    <DateDisplay interval={filters.interval || 'day'} date={people?.day.toString() || ''} />
                </>
            ),
        [filters, people, isInitialLoad]
    )

    const showModalActions = clickhouseFeaturesEnabled && (view === ViewType.TRENDS || view === ViewType.STICKINESS)

    return (
        <Modal
            title={title}
            visible={visible}
            onOk={hidePeople}
            onCancel={hidePeople}
            bodyStyle={{ padding: 0, maxHeight: '60vh', overflowY: 'scroll' }}
            footer={
                <Row gutter={16} justify="end">
                    {people && people.count > 0 && showModalActions && (
                        <>
                            <Col>
                                <Button onClick={onSaveCohort} data-attr="person-modal-save-as-cohort">
                                    <UsergroupAddOutlined />
                                    Save as cohort
                                </Button>
                            </Col>
                            <Col>
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
                            </Col>
                        </>
                    )}
                    <Col>
                        <Button onClick={reloadPeople} loading={loadingMorePeople} icon={<ReloadOutlined />}>
                            Refresh
                        </Button>
                    </Col>
                </Row>
            }
            width={600}
            maskClosable
        >
            {isInitialLoad && (
                <div style={{ padding: 16 }}>
                    <Skeleton active />
                </div>
            )}
            {!isInitialLoad && people && (
                <>
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'flex-start',
                            gap: 16,
                        }}
                    >
                        {!preflight?.is_clickhouse_enabled && (
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
                    </div>
                    <Col style={{ background: '#FAFAFA' }}>
                        {people?.people.map((person) => (
                            <div key={person.id}>
                                <PersonRow person={person} people={people} filters={filters} />
                            </div>
                        ))}
                    </Col>
                    {people?.next && (
                        <div
                            style={{
                                margin: '1rem',
                                textAlign: 'center',
                            }}
                        >
                            <Button type="primary" style={{ color: 'white' }} onClick={loadMorePeople}>
                                {loadingMorePeople ? <Spin /> : 'Load more persons'}
                            </Button>
                        </div>
                    )}
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
        <Col key={person.id} style={{ borderBottom: '1px solid var(--border)' }}>
            <Row style={{ justifyContent: 'space-between', padding: '14px 8px' }}>
                <Row>
                    <ExpandIcon {...expandProps}>{undefined}</ExpandIcon>
                    <Col style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
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
                <Row style={{ padding: '0 16px', background: '#fff', borderTop: '1px solid var(--border-light)' }}>
                    <PropertiesTable properties={person.properties} />
                </Row>
            )}
        </Col>
    )
}
