import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined, UsergroupAddOutlined } from '@ant-design/icons'
import { Modal, Button, Input, Skeleton } from 'antd'
import { FilterType, InsightType, ActorType } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { isGroupType, midEllipsis, pluralize } from 'lib/utils'
import './PersonsModal.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { DateDisplay } from 'lib/components/DateDisplay'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { PersonHeader } from '../persons/PersonHeader'
import api from '../../lib/api'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'
import { IconPersonFilled } from 'lib/components/icons'

export interface PersonsModalProps {
    visible: boolean
    view: InsightType
    filters: Partial<FilterType>
    onSaveCohort: () => void
    showModalActions?: boolean
}

export function PersonsModal({
    visible,
    view,
    filters,
    onSaveCohort,
    showModalActions = true,
}: PersonsModalProps): JSX.Element {
    const {
        people,
        loadingMorePeople,
        firstLoadedPeople,
        searchTerm,
        isInitialLoad,
        clickhouseFeaturesEnabled,
        peopleParams,
        actorLabel,
    } = useValues(personsModalLogic)
    const { hidePeople, loadMorePeople, setFirstLoadedActors, setPersonsModalFilters, setSearchTerm } =
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
            ) : filters.insight === InsightType.FUNNELS ? (
                <>
                    {(people?.funnelStep ?? 0) >= 0 ? 'Completed' : 'Dropped off at'} step{' '}
                    {Math.abs(people?.funnelStep ?? 0)} • <PropertyKeyInfo value={people?.label || ''} disablePopover />{' '}
                    {!!people?.breakdown_value ? `• ${people.breakdown_value}` : ''}
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

    const isDownloadCsvAvailable = view === InsightType.TRENDS && showModalActions
    const isSaveAsCohortAvailable =
        clickhouseFeaturesEnabled &&
        (view === InsightType.TRENDS || view === InsightType.STICKINESS) &&
        showModalActions

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
                                placeholder="Search for persons by email, name, or ID"
                                onChange={(e) => {
                                    setSearchTerm(e.target.value)
                                    if (!e.target.value) {
                                        setFirstLoadedActors(firstLoadedPeople)
                                    }
                                }}
                                value={searchTerm}
                                onSearch={(term) =>
                                    term
                                        ? setPersonsModalFilters(term, people, filters)
                                        : setFirstLoadedActors(firstLoadedPeople)
                                }
                            />
                        )}
                        <div className="user-count-subheader">
                            <IconPersonFilled style={{ fontSize: '1.125rem', marginRight: '0.5rem' }} />
                            <span>
                                This list contains{' '}
                                <b>
                                    {people.count} unique {actorLabel}
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
                            </span>
                        </div>
                        {people.count > 0 ? (
                            <LemonTable
                                columns={
                                    [
                                        {
                                            title: 'Person',
                                            key: 'person',
                                            render: function Render(_, actor: ActorType) {
                                                return <ActorRow actor={actor} />
                                            },
                                        },
                                    ] as LemonTableColumns<ActorType>
                                }
                                className="persons-table"
                                rowKey="id"
                                expandable={{
                                    expandedRowRender: function RenderPropertiesTable({ properties }) {
                                        return Object.keys(properties).length ? (
                                            <PropertiesTable properties={properties} />
                                        ) : (
                                            'This person has no properties.'
                                        )
                                    },
                                }}
                                embedded
                                showHeader={false}
                                dataSource={people.people}
                                nouns={['person', 'persons']}
                            />
                        ) : (
                            <div className="person-row-container person-row">
                                We couldn't find any matching persons for this data point.
                            </div>
                        )}
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
    actor: ActorType
}

export function ActorRow({ actor }: ActorRowProps): JSX.Element {
    if (isGroupType(actor)) {
        return (
            <div key={actor.id} className="person-row">
                <div className="person-ids">
                    <strong>
                        <GroupActorHeader actor={actor} />
                    </strong>
                </div>
            </div>
        )
    } else {
        return (
            <div key={actor.id} className="person-ids">
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
        )
    }
}
