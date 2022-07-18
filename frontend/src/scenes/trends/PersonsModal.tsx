import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined, UsergroupAddOutlined } from '@ant-design/icons'
import { Button, Input, Modal, Select, Skeleton } from 'antd'
import { ActorType, ChartDisplayType, ExporterFormat, FilterType, InsightType } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import './PersonsModal.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { DateDisplay } from 'lib/components/DateDisplay'
import { PersonHeader } from '../persons/PersonHeader'
import api from '../../lib/api'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'
import { IconPersonFilled } from 'lib/components/icons'
import { InsightLabel } from 'lib/components/InsightLabel'
import { getSeriesColor } from 'lib/colors'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { SessionPlayerDrawer } from 'scenes/session-recordings/SessionPlayerDrawer'
import { MultiRecordingButton } from 'scenes/session-recordings/multiRecordingButton/multiRecordingButton'
import { countryCodeToFlag, countryCodeToName } from 'scenes/insights/views/WorldMap/countryCodes'
import { triggerExport } from 'lib/components/ExportButton/exporter'

export interface PersonsModalProps {
    visible: boolean
    view: InsightType
    filters: Partial<FilterType>
    onSaveCohort: () => void
    showModalActions?: boolean
    aggregationTargetLabel: { singular: string; plural: string }
}

export function PersonsModal({
    visible,
    view,
    filters,
    onSaveCohort,
    showModalActions = true,
    aggregationTargetLabel,
}: PersonsModalProps): JSX.Element {
    const {
        people,
        loadingMorePeople,
        firstLoadedPeople,
        searchTerm,
        isInitialLoad,
        peopleParams,
        actorLabel,
        sessionRecordingId,
    } = useValues(personsModalLogic)
    const {
        hidePeople,
        loadMorePeople,
        setFirstLoadedActors,
        setPersonsModalFilters,
        setSearchTerm,
        switchToDataPoint,
        openRecordingModal,
        closeRecordingModal,
    } = useActions(personsModalLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const title = useMemo(
        () =>
            isInitialLoad ? (
                `Loading ${aggregationTargetLabel.plural}…`
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
            ) : filters.display === ChartDisplayType.WorldMap ? (
                <>
                    {capitalizeFirstLetter(actorLabel)}
                    {peopleParams?.breakdown_value
                        ? ` in ${countryCodeToFlag(peopleParams?.breakdown_value as string)} ${
                              countryCodeToName[peopleParams?.breakdown_value as string]
                          }`
                        : ''}
                </>
            ) : (
                <>
                    {capitalizeFirstLetter(actorLabel)} on{' '}
                    <DateDisplay interval={filters.interval || 'day'} date={people?.day?.toString() || ''} />
                </>
            ),
        [filters, people, isInitialLoad]
    )

    const flaggedInsights = featureFlags[FEATURE_FLAGS.NEW_INSIGHT_COHORTS]
    const isDownloadCsvAvailable: boolean =
        !!featureFlags[FEATURE_FLAGS.ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS] &&
        !!featureFlags[FEATURE_FLAGS.PERSON_MODAL_EXPORTS] &&
        InsightType.TRENDS &&
        showModalActions &&
        !!people?.action
    const isSaveAsCohortAvailable =
        (view === InsightType.TRENDS ||
            view === InsightType.STICKINESS ||
            (!!flaggedInsights && (view === InsightType.FUNNELS || view === InsightType.PATHS))) && // make sure flaggedInsights isn't evaluated as undefined
        showModalActions

    const showCountedByTag = !!people?.crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    const hasMultipleSeries = !!people?.crossDataset?.find(({ action }) => action?.order)
    return (
        <>
            {!!sessionRecordingId && <SessionPlayerDrawer onClose={closeRecordingModal} />}
            <Modal
                title={title}
                visible={visible}
                onCancel={hidePeople}
                footer={
                    people &&
                    people.count > 0 &&
                    (isDownloadCsvAvailable || isSaveAsCohortAvailable) && (
                        <>
                            {isDownloadCsvAvailable && (
                                <Button
                                    icon={<DownloadOutlined />}
                                    onClick={() => {
                                        triggerExport({
                                            export_format: ExporterFormat.CSV,
                                            export_context: {
                                                path: api.actions.determinePeopleCsvUrl(
                                                    {
                                                        label: people.label,
                                                        action: people.action,
                                                        date_from: people.day,
                                                        date_to: people.day,
                                                        breakdown_value: people.breakdown_value,
                                                    },
                                                    filters,
                                                    !!featureFlags[FEATURE_FLAGS.ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS]
                                                ),
                                            },
                                        })
                                    }}
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
                            {!!people.crossDataset?.length && people.seriesId !== undefined && (
                                <div className="data-point-selector">
                                    <Select value={people.seriesId} onChange={(_id) => switchToDataPoint(_id)}>
                                        {people.crossDataset.map((dataPoint) => (
                                            <Select.Option
                                                value={dataPoint.id}
                                                key={`${dataPoint.action?.id}${dataPoint.breakdown_value}`}
                                            >
                                                <InsightLabel
                                                    seriesColor={getSeriesColor(dataPoint.id)}
                                                    action={dataPoint.action}
                                                    breakdownValue={
                                                        dataPoint.breakdown_value === ''
                                                            ? 'None'
                                                            : dataPoint.breakdown_value?.toString()
                                                    }
                                                    showCountedByTag={showCountedByTag}
                                                    hasMultipleSeries={hasMultipleSeries}
                                                />
                                            </Select.Option>
                                        ))}
                                    </Select>
                                </div>
                            )}
                            <div className="user-count-subheader">
                                <IconPersonFilled style={{ fontSize: '1.125rem', marginRight: '0.5rem' }} />
                                <span>
                                    This list contains{' '}
                                    <b>
                                        {people.count} unique {aggregationTargetLabel.plural}
                                    </b>
                                    {peopleParams?.pointValue !== undefined &&
                                        (!peopleParams.action?.math || peopleParams.action?.math === 'total') && (
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
                                            {
                                                width: 0,
                                                title: 'Recordings',
                                                key: 'recordings',
                                                render: function Render(_, actor: ActorType) {
                                                    if (
                                                        actor.matched_recordings?.length &&
                                                        actor.matched_recordings?.length > 0
                                                    ) {
                                                        return (
                                                            <MultiRecordingButton
                                                                sessionRecordings={actor.matched_recordings}
                                                                onOpenRecording={(sessionRecording) => {
                                                                    openRecordingModal(sessionRecording.session_id)
                                                                }}
                                                            />
                                                        )
                                                    }
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
                                    We couldn't find any matching {aggregationTargetLabel.plural} for this data point.
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
                                        Load more {aggregationTargetLabel.plural}
                                    </Button>
                                </div>
                            )}
                        </>
                    )
                )}
            </Modal>
        </>
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
