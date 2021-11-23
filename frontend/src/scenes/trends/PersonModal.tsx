import React, { useMemo, useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined, UsergroupAddOutlined, UserOutlined } from '@ant-design/icons'
import { Modal, Button, Input, Skeleton } from 'antd'
import { FilterType, PersonType, InsightType, GroupActorType } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { isGroupType, midEllipsis, pluralize } from 'lib/utils'
import './PersonModal.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { ExpandIcon, ExpandIconProps } from 'lib/components/ExpandIcon'
import { DateDisplay } from 'lib/components/DateDisplay'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { PersonHeader } from '../persons/PersonHeader'
import api from '../../lib/api'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'

export interface PersonModalProps {
    visible: boolean
    view: InsightType
    filters: Partial<FilterType>
    onSaveCohort: () => void
    showPersonsModalActions?: boolean
}

export function PersonModal({
    visible,
    view,
    filters,
    onSaveCohort,
    showPersonsModalActions = true,
}: PersonModalProps): JSX.Element {
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
    const _isGroupType = people?.people?.[0] && isGroupType(people.people[0])

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
            ) : filters.insight === InsightType.FUNNELS ? (
                <>
                    {(people?.funnelStep ?? 0) >= 0 ? 'Completed' : 'Dropped off at'} step{' '}
                    {Math.abs(people?.funnelStep ?? 0)} - <PropertyKeyInfo value={people?.label || ''} disablePopover />{' '}
                    {people?.breakdown_value !== undefined &&
                        `- ${people.breakdown_value ? people.breakdown_value : 'None'}`}
                </>
            ) : filters.insight === InsightType.PATHS ? (
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

    const isDownloadCsvAvailable = view === InsightType.TRENDS && showPersonsModalActions
    const isSaveAsCohortAvailable =
        clickhouseFeaturesEnabled &&
        (view === InsightType.TRENDS || view === InsightType.STICKINESS) &&
        showPersonsModalActions

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
                                {people.count} unique{' '}
                                {pluralize(people.count, _isGroupType ? 'group' : 'user', undefined, false)}
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
                                people?.people.map((actor) => (
                                    <div key={actor.id}>
                                        <ActorRow actor={actor} />
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

interface ActorRowProps {
    actor: PersonType | GroupActorType
}

export function ActorRow({ actor }: ActorRowProps): JSX.Element {
    const [showProperties, setShowProperties] = useState(false)
    const expandProps = {
        record: '',
        onExpand: () => setShowProperties(!showProperties),
        expanded: showProperties,
        expandable: Object.keys(actor.properties).length > 0,
        prefixCls: 'ant-table',
    } as ExpandIconProps

    if (isGroupType(actor)) {
        return (
            <div key={actor.id} className="person-row-container">
                <div className="person-row">
                    <ExpandIcon {...expandProps} />
                    <div className="person-ids">
                        <strong>
                            <GroupActorHeader actor={actor} withIcon={false} />
                        </strong>
                    </div>
                </div>
                {showProperties && (
                    <PropertiesTable properties={actor.properties} className="person-modal-properties" />
                )}
            </div>
        )
    } else {
        return (
            <div key={actor.id} className="person-row-container">
                <div className="person-row">
                    <ExpandIcon {...expandProps} />
                    <div className="person-ids">
                        <strong>
                            <PersonHeader person={actor} withIcon={false} />
                        </strong>
                        <CopyToClipboardInline
                            explicitValue={actor.distinct_ids[0]}
                            iconStyle={{ color: 'var(--primary)' }}
                            iconPosition="end"
                            className="text-small text-muted-alt"
                        >
                            {midEllipsis(actor.distinct_ids[0], 32)}
                        </CopyToClipboardInline>
                    </div>
                </div>
                {showProperties && (
                    <PropertiesTable properties={actor.properties} className="person-modal-properties" />
                )}
            </div>
        )
    }
}
