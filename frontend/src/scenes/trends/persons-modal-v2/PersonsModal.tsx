import React, { useState } from 'react'
import { useActions, useValues } from 'kea'
import { DownloadOutlined } from '@ant-design/icons'
import { ActorType, ExporterFormat } from '~/types'
import { personsModalLogic } from './personsModalLogic'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { isGroupType, Loading, midEllipsis } from 'lib/utils'
import './PersonsModal.scss'
import { PropertiesTable } from 'lib/components/PropertiesTable'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { GroupActorHeader } from 'scenes/persons/GroupActorHeader'
import { IconPersonFilled } from 'lib/components/icons'
import { MultiRecordingButton } from 'scenes/session-recordings/multiRecordingButton/multiRecordingButton'
import { triggerExport } from 'lib/components/ExportButton/exporter'
import { LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import ReactDOM from 'react-dom'
import { Skeleton } from 'antd'

export interface PersonsModalProps {
    onAfterClose?: () => void
    url: string
    title: React.ReactNode
}

export function PersonsModalV2({
    // isOpen,
    // view,
    // filters,
    // onSaveCohort,
    // showModalActions = true,
    // aggregationTargetLabel,
    url,
    title,
    onAfterClose,
}: PersonsModalProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(true)
    const logic = personsModalLogic({ url })

    const { allPeople, peopleLoading, people: peopleRes, searchTerm } = useValues(logic)
    const { loadPeople, setSearchTerm } = useActions(logic)

    // const {
    //     people,
    //     loadingMorePeople,
    //     firstLoadedPeople,
    //     searchTerm,
    //     isInitialLoad,
    //     peopleParams,
    //     actorLabel,
    //     sessionRecordingId,
    // } = useValues(personsModalLogic)
    // const {
    //     hidePeople,
    //     loadMorePeople,
    //     setFirstLoadedActors,
    //     setPersonsModalFilters,
    //     setSearchTerm,
    //     switchToDataPoint,
    //     openRecordingModal,
    //     closeRecordingModal,
    // } = useActions(personsModalLogic)
    // const { featureFlags } = useValues(featureFlagLogic)

    // const title = useMemo(
    //     () =>
    //         isInitialLoad ? (
    //             `Loading ${aggregationTargetLabel.plural}…`
    //         ) : filters.shown_as === 'Stickiness' ? (
    //             <>
    //                 <PropertyKeyInfo value={people?.label || ''} disablePopover /> stickiness on day {people?.day}
    //             </>
    //         ) : filters.display === ChartDisplayType.ActionsBarValue ||
    //           filters.display === ChartDisplayType.ActionsPie ||
    //           filters.display === ChartDisplayType.BoldNumber ? (
    //             <PropertyKeyInfo value={people?.label || ''} disablePopover />
    //         ) : filters.insight === InsightType.FUNNELS ? (
    //             <>
    //                 {(people?.funnelStep ?? 0) >= 0 ? 'Completed' : 'Dropped off at'} step{' '}
    //                 {Math.abs(people?.funnelStep ?? 0)} • <PropertyKeyInfo value={people?.label || ''} disablePopover />{' '}
    //                 {!!people?.breakdown_value ? `• ${people.breakdown_value}` : ''}
    //             </>
    //         ) : filters.insight === InsightType.PATHS ? (
    //             <>
    //                 {people?.pathsDropoff ? 'Dropped off after' : 'Completed'} step{' '}
    //                 <PropertyKeyInfo value={people?.label.replace(/(^[0-9]+_)/, '') || ''} disablePopover />
    //             </>
    //         ) : filters.display === ChartDisplayType.WorldMap ? (
    //             <>
    //                 {capitalizeFirstLetter(actorLabel)}
    //                 {peopleParams?.breakdown_value
    //                     ? ` in ${countryCodeToFlag(peopleParams?.breakdown_value as string)} ${
    //                           countryCodeToName[peopleParams?.breakdown_value as string]
    //                       }`
    //                     : ''}
    //             </>
    //         ) : (
    //             <>
    //                 {capitalizeFirstLetter(actorLabel)} on{' '}
    //                 <DateDisplay interval={filters.interval || 'day'} date={people?.day?.toString() || ''} />
    //             </>
    //         ),
    //     [filters, people, isInitialLoad]
    // )

    // const flaggedInsights = featureFlags[FEATURE_FLAGS.NEW_INSIGHT_COHORTS]
    // const isDownloadCsvAvailable: boolean =
    //     !!featureFlags[FEATURE_FLAGS.PERSON_MODAL_EXPORTS] && InsightType.TRENDS && showModalActions && !!people?.action
    // const isSaveAsCohortAvailable =
    //     (view === InsightType.TRENDS ||
    //         view === InsightType.STICKINESS ||
    //         (!!flaggedInsights && (view === InsightType.FUNNELS || view === InsightType.PATHS))) && // make sure flaggedInsights isn't evaluated as undefined
    //     showModalActions

    // const showCountedByTag = !!people?.crossDataset?.find(({ action }) => action?.math && action.math !== 'total')
    // const hasMultipleSeries = !!people?.crossDataset?.find(({ action }) => action?.order)

    // const filterSearchResults = (): void => {
    //     if (!searchTerm) {
    //         setFirstLoadedActors(firstLoadedPeople)
    //     }
    //     people && setPersonsModalFilters(searchTerm, people, filters)
    // }

    return (
        <>
            {/* {!!sessionRecordingId && <SessionPlayerDrawer onClose={closeRecordingModal} />} */}
            <LemonModal
                title={title}
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                onAfterClose={onAfterClose}
                description={
                    <>
                        <LemonInput
                            type="search"
                            placeholder="Search for persons by email, name, or ID"
                            fullWidth
                            value={searchTerm}
                            onChange={setSearchTerm}
                            // disabled={isInitialLoad}
                            className="my-2"
                        />

                        {peopleLoading ? (
                            <Skeleton active paragraph={false} />
                        ) : (
                            <div className="flex items-center gap-2">
                                <IconPersonFilled className="text-xl" />
                                <span>
                                    This list contains <b>{peopleRes?.total_count} unique results</b>.
                                </span>
                            </div>
                        )}
                    </>
                }
                footer={
                    <>
                        <LemonButton
                            icon={<DownloadOutlined />}
                            type="secondary"
                            onClick={() => {
                                triggerExport({
                                    export_format: ExporterFormat.CSV,
                                    export_context: {
                                        path: url,
                                    },
                                })
                            }}
                            data-attr="person-modal-download-csv"
                        >
                            Download CSV
                        </LemonButton>
                    </>
                }
                width={600}
            >
                <div>
                    {peopleLoading ? <Loading /> : null}

                    {allPeople && allPeople.length > 0 ? (
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
                                                            console.log(sessionRecording)
                                                            // openRecordingModal(sessionRecording.session_id)
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
                            dataSource={allPeople}
                            nouns={['person', 'persons']}
                        />
                    ) : (
                        <div className="person-row-container person-row">
                            We couldn't find any matching results for this data point.
                        </div>
                    )}
                </div>

                {peopleRes?.next && (
                    <div className="m-4 flex justify-center">
                        <LemonButton
                            type="primary"
                            onClick={() => peopleRes?.next && loadPeople({ url: peopleRes?.next })}
                            loading={peopleLoading}
                        >
                            Load more
                        </LemonButton>
                    </div>
                )}

                {/* {isInitialLoad ? (
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
                )} */}
            </LemonModal>
        </>
    )
}

export type OpenPersonsModalProps = Omit<PersonsModalProps, 'onClose' | 'onAfterClose'>

export const openPersonsModal = (props: OpenPersonsModalProps): void => {
    // const featureFlags = featureFlagLogic.findMounted()?.values?.featureFlags

    // if (!featureFlags || !featureFlags[FEATURE_FLAGS.PERSONS_MODAL_V2]) {
    //     // Currrently this will display 2 modals, as we want to test this comparison in production
    //     return
    // }

    const div = document.createElement('div')
    function destroy(): void {
        const unmountResult = ReactDOM.unmountComponentAtNode(div)
        if (unmountResult && div.parentNode) {
            div.parentNode.removeChild(div)
        }
    }

    document.body.appendChild(div)
    ReactDOM.render(<PersonsModalV2 {...props} onAfterClose={destroy} />, div)
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
