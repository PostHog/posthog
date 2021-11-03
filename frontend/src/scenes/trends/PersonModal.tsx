import React, { useMemo, useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined, UsergroupAddOutlined, UserOutlined } from '@ant-design/icons'
import { Modal, Button, Input, Skeleton } from 'antd'
import { FilterType, PersonType, ViewType } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { midEllipsis, pluralize } from 'lib/utils'
import './PersonModal.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ExpandIcon, ExpandIconProps } from 'lib/components/ExpandIcon'
import { DateDisplay } from 'lib/components/DateDisplay'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { PersonHeader } from '../persons/PersonHeader'
import api from '../../lib/api'

export interface PersonModalProps {
    visible: boolean
    view: ViewType
    filters: Partial<FilterType>
    onSaveCohort: () => void
}

export function PersonModal({ visible, view, filters, onSaveCohort }: PersonModalProps): JSX.Element {
    const {
        people,
        loadingMorePeople,
        firstLoadedPeople,
        searchTerm,
        isInitialLoad,
        clickhouseFeaturesEnabled,
        peopleParams,
    } = useValues(personsModalLogic)
    const { hidePeople, loadMorePeople, setFirstLoadedPeople, setPersonsModalFilters, setSearchTerm } =
        useActions(personsModalLogic)
    const { preflight } = useValues(preflightLogic)

    const title = useMemo(
        () =>
            isInitialLoad ? (
                'Loading persons…'
            ) : filters.shown_as === 'Stickiness' ? (
                <>
                    <PropertyKeyInfo value={people?.label || ''} disablePopover /> stickiness on day {people?.day}
                </>
            ) : filters.display === 'ActionsBarValue' || filters.display === 'ActionsPie' ? (
                <PropertyKeyInfo value={people?.label || ''} disablePopover />
            ) : filters.insight === ViewType.FUNNELS ? (
                <>
                    {(people?.funnelStep ?? 0) >= 0 ? 'Completed' : 'Dropped off at'} step{' '}
                    {Math.abs(people?.funnelStep ?? 0)} - <PropertyKeyInfo value={people?.label || ''} disablePopover />{' '}
                    {people?.breakdown_value !== undefined &&
                        `- ${people.breakdown_value ? people.breakdown_value : 'None'}`}
                </>
            ) : filters.insight === ViewType.PATHS ? (
                <>
                    {people?.pathsDropoff ? 'Dropped off after' : 'Completed'} step{' '}
                    <PropertyKeyInfo value={people?.label.replace(/(^[0-9]+_)/, '') || ''} disablePopover />
                </>
            ) : (
                <>
                    <PropertyKeyInfo value={people?.label || ''} disablePopover /> on{' '}
                    <DateDisplay interval={filters.interval || 'day'} date={people?.day?.toString() || ''} />
                </>
            ),
        [filters, people, isInitialLoad]
    )

    const isDownloadCsvAvailable = view === ViewType.TRENDS
    const isSaveAsCohortAvailable = clickhouseFeaturesEnabled

    return (
        <Modal
            title={title}
            visible={visible}
            onOk={hidePeople}
            onCancel={hidePeople}
            footer={
                people &&
                people.count > 0 &&
                (isDownloadCsvAvailable || isSaveAsCohortAvailable) && (
                    <>
                        {isDownloadCsvAvailable && (
                            <Button
                                icon={<DownloadOutlined />}
                                href={api.actions.determinePeopleCsvUrl(
                                    {
                                        label: people.label,
                                        action: people.action,
                                        date_from: people.day,
                                        date_to: people.day,
                                        breakdown_value: people.breakdown_value,
                                    },
                                    filters
                                )}
                                style={{ marginRight: 8 }}
                                data-attr="person-modal-download-csv"
                            >
                                Download CSV
                            </Button>
                        )}
                        {isSaveAsCohortAvailable && (
                            <Button
                                onClick={onSaveCohort}
                                icon={<UsergroupAddOutlined />}
                                data-attr="person-modal-save-as-cohort"
                            >
                                Save as cohort
                            </Button>
                        )}
                    </>
                )
            }
            width={600}
            className="person-modal"
        >
            {isInitialLoad ? (
                <div style={{ padding: 16 }}>
                    <Skeleton active />
                </div>
            ) : (
                people && (
                    <>
                        {!preflight?.is_clickhouse_enabled && (
                            <Input.Search
                                allowClear
                                enterButton
                                placeholder="Search person by email, name, or ID"
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
                        <div className="user-count-subheader">
                            <UserOutlined /> This list contains{' '}
                            <b>
                                {people.count} unique {pluralize(people.count, 'user', undefined, false)}
                            </b>
                            {peopleParams?.pointValue !== undefined &&
                                peopleParams.action !== 'session' &&
                                (!peopleParams.action.math || peopleParams.action.math === 'total') && (
                                    <>
                                        {' '}
                                        who performed the event{' '}
                                        <b>
                                            {peopleParams.pointValue} total{' '}
                                            {pluralize(peopleParams.pointValue, 'time', undefined, false)}
                                        </b>
                                    </>
                                )}
                            .
                        </div>
                        <div style={{ background: '#FAFAFA' }}>
                            {people.count > 0 ? (
                                people?.people.map((person) => (
                                    <div key={person.id}>
                                        <PersonRow person={person} />
                                    </div>
                                ))
                            ) : (
                                <div className="person-row-container person-row">
                                    We couldn't find any matching persons for this data point.
                                </div>
                            )}
                        </div>
                        {people?.next && (
                            <div
                                style={{
                                    margin: '1rem',
                                    textAlign: 'center',
                                }}
                            >
                                <Button
                                    type="primary"
                                    style={{ color: 'white' }}
                                    onClick={loadMorePeople}
                                    loading={loadingMorePeople}
                                >
                                    Load more people
                                </Button>
                            </div>
                        )}
                    </>
                )
            )}
        </Modal>
    )
}

interface PersonRowProps {
    person: PersonType
}

export function PersonRow({ person }: PersonRowProps): JSX.Element {
    const [showProperties, setShowProperties] = useState(false)
    const expandProps = {
        record: '',
        onExpand: () => setShowProperties(!showProperties),
        expanded: showProperties,
        expandable: Object.keys(person.properties).length > 0,
        prefixCls: 'ant-table',
    } as ExpandIconProps

    return (
        <div key={person.id} className="person-row-container">
            <div className="person-row">
                <ExpandIcon {...expandProps} />
                <div className="person-ids">
                    <strong>
                        <PersonHeader person={person} withIcon={false} />
                    </strong>
                    <CopyToClipboardInline
                        explicitValue={person.distinct_ids[0]}
                        iconStyle={{ color: 'var(--primary)' }}
                        iconPosition="end"
                        className="text-small text-muted-alt"
                    >
                        {midEllipsis(person.distinct_ids[0], 32)}
                    </CopyToClipboardInline>
                </div>
            </div>
            {showProperties && <PropertiesTable properties={person.properties} className="person-modal-properties" />}
        </div>
    )
}
