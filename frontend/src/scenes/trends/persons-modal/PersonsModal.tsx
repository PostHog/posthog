import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined } from '@ant-design/icons'
import { Skeleton } from 'antd'
import { ActorType, ChartDisplayType, ExporterFormat, FilterType, InsightType } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { capitalizeFirstLetter, isGroupType, midEllipsis, pluralize } from 'lib/utils'
import './PersonsModal.scss'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { DateDisplay } from 'lib/components/DateDisplay'
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
import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { AlertMessage } from 'lib/components/AlertMessage'
import { sessionPlayerDrawerLogic } from 'scenes/session-recordings/sessionPlayerDrawerLogic'
import api from 'lib/api'
import { PersonHeader } from 'scenes/persons/PersonHeader'

export interface PersonsModalProps {
    isOpen: boolean
    view: InsightType
    filters: Partial<FilterType>
    onSaveCohort: () => void
    showModalActions?: boolean
    aggregationTargetLabel: { singular: string; plural: string }
}

export function PersonsModal({
    isOpen,
    view,
    filters,
    onSaveCohort,
    showModalActions = true,
    aggregationTargetLabel,
}: PersonsModalProps): JSX.Element {
    const { people, loadingMorePeople, firstLoadedPeople, searchTerm, isInitialLoad, peopleParams, actorLabel } =
        useValues(personsModalLogic)
    const {
        hidePeople,
        loadMorePeople,
        setFirstLoadedActors,
        setPersonsModalFilters,
        setSearchTerm,
        switchToDataPoint,
    } = useActions(personsModalLogic)
    const { openSessionPlayer, closeSessionPlayer } = useActions(sessionPlayerDrawerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const title = useMemo(
        () =>
            isInitialLoad ? (
                `Loading ${aggregationTargetLabel.plural}…`
            ) : filters.shown_as === 'Stickiness' ? (
                <>
                    <PropertyKeyInfo value={people?.label || ''} disablePopover /> stickiness on day {people?.day}
                </>
            ) : filters.display === ChartDisplayType.ActionsBarValue ||
              filters.display === ChartDisplayType.ActionsPie ||
              filters.display === ChartDisplayType.BoldNumber ? (
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
        !!featureFlags[FEATURE_FLAGS.PERSON_MODAL_EXPORTS] && InsightType.TRENDS && showModalActions && !!people?.action
    const isSaveAsCohortAvailable =
        (view === InsightType.TRENDS ||
            view === InsightType.STICKINESS ||
            (!!flaggedInsights && (view === InsightType.FUNNELS || view === InsightType.PATHS))) && // make sure flaggedInsights isn't evaluated as undefined
        showModalActions

    const showCountedByTag = !!people?.crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    const hasMultipleSeries = !!people?.crossDataset?.find(({ action }) => action?.order)

    const filterSearchResults = (): void => {
        if (!searchTerm) {
            setFirstLoadedActors(firstLoadedPeople)
        }
        people && setPersonsModalFilters(searchTerm, people, filters)
    }

    return (
        <>
            <LemonModal
                title={title}
                isOpen={isOpen}
                onClose={hidePeople}
                footer={
                    people &&
                    people.count > 0 &&
                    (isDownloadCsvAvailable || isSaveAsCohortAvailable) && (
                        <div className="flex gap-2">
                            {isDownloadCsvAvailable && (
                                <LemonButton
                                    icon={<DownloadOutlined />}
                                    type="secondary"
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
                                                    filters
                                                ),
                                            },
                                        })
                                    }}
                                    data-attr="person-modal-download-csv"
                                >
                                    Download CSV
                                </LemonButton>
                            )}
                            {isSaveAsCohortAvailable && (
                                <LemonButton
                                    onClick={onSaveCohort}
                                    type="secondary"
                                    data-attr="person-modal-save-as-cohort"
                                >
                                    Save as cohort
                                </LemonButton>
                            )}
                        </div>
                    )
                }
                width={600}
            >
                {people && !!people.missingPersons && (
                    <AlertMessage type="info" className="mb-2">
                        {people.missingPersons}{' '}
                        {people.missingPersons > 1
                            ? `${aggregationTargetLabel.plural} are`
                            : `${aggregationTargetLabel.singular} is`}{' '}
                        not shown because they've been lost.{' '}
                        <a href="https://posthog.com/docs/how-posthog-works/queries#insights-counting-unique-persons">
                            Read more here for when this can happen
                        </a>
                        .
                    </AlertMessage>
                )}
                <LemonInput
                    type="search"
                    placeholder="Search for persons by email, name, or ID"
                    fullWidth
                    onChange={(value) => {
                        setSearchTerm(value)
                    }}
                    onBlur={() => filterSearchResults()}
                    onPressEnter={() => filterSearchResults()}
                    value={searchTerm}
                    disabled={isInitialLoad}
                    className="mb-2"
                />
                {isInitialLoad ? (
                    <div className="p-4">
                        <Skeleton active />
                    </div>
                ) : (
                    <>
                        {people && (
                            <>
                                {!!people.crossDataset?.length && people.seriesId !== undefined && (
                                    <LemonSelect
                                        fullWidth
                                        className="mb-2"
                                        value={String(people.seriesId)}
                                        onChange={(_id) =>
                                            typeof _id === 'string' ? switchToDataPoint(parseInt(_id, 10)) : null
                                        }
                                        options={people.crossDataset.map((dataPoint) => ({
                                            value: `${dataPoint.id}`,
                                            label: (
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
                                            ),
                                        }))}
                                    />
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
                                                                        openSessionPlayer(sessionRecording.session_id)
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
                                        We couldn't find any matching {aggregationTargetLabel.plural} for this data
                                        point.
                                    </div>
                                )}
                                {people?.next && (
                                    <div className="m-4 flex justify-center">
                                        <LemonButton
                                            type="primary"
                                            size="small"
                                            onClick={loadMorePeople}
                                            loading={loadingMorePeople}
                                        >
                                            Load more {aggregationTargetLabel.plural}
                                        </LemonButton>
                                    </div>
                                )}
                            </>
                        )}
                    </>
                )}
            </LemonModal>
            <SessionPlayerDrawer onClose={closeSessionPlayer} />
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
                    className="text-xs text-muted-alt"
                >
                    {midEllipsis(actor.distinct_ids[0], 32)}
                </CopyToClipboardInline>
            </div>
        )
    }
}
