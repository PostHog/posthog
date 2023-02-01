import { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { EventDetails } from 'scenes/events/EventDetails'
import { Link } from 'lib/lemon-ui/Link'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { autoCaptureEventToDescription, insightUrlForEvent } from 'lib/utils'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { TZLabel } from 'lib/components/TZLabel'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { ActionType, AnyPropertyFilter, ColumnChoice, EventsTableRowItem } from '~/types'
import { LemonEventName } from 'scenes/actions/EventName'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import clsx from 'clsx'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { urls } from 'scenes/urls'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { TableCellRepresentation } from 'lib/lemon-ui/LemonTable/types'
import { IconExport, IconPlayCircle, IconSync } from 'lib/lemon-ui/icons'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'
import { createActionFromEvent } from './createActionFromEvent'
import { usePageVisibility } from 'lib/hooks/usePageVisibility'
import { LemonTableConfig } from 'lib/components/ResizableTable/TableConfig'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { EventBufferNotice } from './EventBufferNotice'
import { LemonDivider } from '@posthog/lemon-ui'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { ExportWithConfirmation } from '~/queries/nodes/DataTable/ExportWithConfirmation'

export interface FixedFilters {
    action_id?: ActionType['id']
    event_filter?: string
    person_id?: string | number
    distinct_ids?: string[]
    properties?: AnyPropertyFilter[]
}

interface EventsTableProps {
    pageKey: string
    fixedFilters?: FixedFilters
    fixedColumns?: LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined>[]
    sceneUrl?: string
    fetchMonths?: number
    startingColumns?: ColumnChoice
    showCustomizeColumns?: boolean
    showExport?: boolean
    showAutoload?: boolean
    showEventFilter?: boolean
    showPropertyFilter?: boolean
    showRowExpanders?: boolean
    showActionsButton?: boolean
    showPersonColumn?: boolean
    linkPropertiesToFilters?: boolean
    'data-attr'?: string
}

export function EventsTable({
    pageKey,
    fixedFilters,
    fixedColumns,
    sceneUrl,
    // How many months of data to fetch?
    fetchMonths = 12,
    startingColumns,
    // disableLinkingPropertiesToFilters,

    showCustomizeColumns = true,
    showExport = true,
    showAutoload = true,
    showEventFilter = true,
    showPropertyFilter = true,
    showRowExpanders = true,
    showActionsButton = true,
    showPersonColumn = true,
    linkPropertiesToFilters = true,
    'data-attr': dataAttr,
}: EventsTableProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const logic = eventsTableLogic({
        fixedFilters,
        key: pageKey,
        sceneUrl: sceneUrl || urls.events(),
        fetchMonths,
    })
    const {
        properties,
        eventsFormatted,
        isLoading,
        hasNext,
        isLoadingNext,
        eventFilter,
        automaticLoadEnabled,
        highlightEvents,
        months,
    } = useValues(logic)
    const { tableWidth, selectedColumns } = useValues(
        tableConfigLogic({
            startingColumns: (currentTeam && currentTeam.live_events_columns) ?? startingColumns,
        })
    )

    const {
        fetchNextEvents,
        prependNewEvents,
        setEventFilter,
        toggleAutomaticLoad,
        startDownload,
        setPollingActive,
        setProperties,
    } = useActions(logic)

    const showLinkToPerson = !fixedFilters?.person_id

    const { reportEventsTablePollingReactedToPageVisibility } = useActions(eventUsageLogic)

    const { openSessionPlayer } = useActions(sessionPlayerModalLogic)

    usePageVisibility((pageIsVisible) => {
        setPollingActive(pageIsVisible)
        reportEventsTablePollingReactedToPageVisibility(pageIsVisible)
    })

    const newEventsRender = (
        { date_break, new_events }: EventsTableRowItem,
        colSpan: number
    ): TableCellRepresentation => {
        return {
            children:
                date_break ||
                (new_events ? (
                    <LemonButton icon={<IconSync />} onClick={() => prependNewEvents()} center fullWidth>
                        There are new events. Click here to load them
                    </LemonButton>
                ) : (
                    '???'
                )),
            props: {
                colSpan: colSpan + 1,
                style: new_events ? { padding: 0 } : undefined,
            },
        }
    }

    const personColumn: LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined> = {
        title: 'Person',
        key: 'person',
        render: function renderPerson(_, { event }: EventsTableRowItem) {
            if (!event) {
                return { props: { colSpan: 0 } }
            }
            return showLinkToPerson && event.person?.distinct_ids?.length ? (
                <Link to={urls.person(event.person.distinct_ids[0])}>
                    <PersonHeader noLink withIcon person={event.person} />
                </Link>
            ) : (
                <PersonHeader withIcon person={event.person} />
            )
        },
    }

    const defaultColumns = useMemo(() => {
        const _localColumns: LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined>[] = [
            {
                title: 'Event',
                key: 'event',
                width: '16rem',
                render: function render(_, item: EventsTableRowItem) {
                    if (!item.event) {
                        return newEventsRender(item, tableWidth)
                    }
                    const { event } = item
                    const content = <PropertyKeyInfo value={autoCaptureEventToDescription(event)} />

                    const url = event.properties.$sentry_url

                    return url ? (
                        <Link to={url} target="_blank">
                            {content}
                        </Link>
                    ) : (
                        content
                    )
                },
            },
            {
                title: 'URL / Screen',
                key: 'url',
                width: '4rem',
                render: function renderURL(_, { event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }
                    const param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                    if (linkPropertiesToFilters) {
                        return (
                            <FilterPropertyLink
                                className="ph-no-capture"
                                property={param}
                                value={event.properties[param] as string}
                                filters={{ properties }}
                            />
                        )
                    }
                    return <Property value={event.properties[param]} />
                },
            },
            {
                title: (
                    <Tooltip title='This is the "Library" property on events. Sent by the SDK as "$lib"'>
                        Source
                    </Tooltip>
                ),
                key: 'source',
                render: function renderSource(_, { event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }
                    if (linkPropertiesToFilters) {
                        return (
                            <FilterPropertyLink
                                property="$lib"
                                value={event.properties['$lib'] as string}
                                filters={{ properties }}
                            />
                        )
                    }
                    return <Property value={event.properties['$lib']} />
                },
            },
        ]
        if (showPersonColumn) {
            _localColumns.splice(1, 0, personColumn)
        }
        return _localColumns
    }, [tableWidth])

    const columns = useMemo(() => {
        let columnsSoFar: LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined>[]
        if (selectedColumns === 'DEFAULT') {
            columnsSoFar = [...defaultColumns]
        } else {
            let columnsToBeMapped = !showPersonColumn
                ? selectedColumns.filter((column) => column !== 'person')
                : selectedColumns
            // If user has saved `timestamp`, a column only used in the Data Exploration flagged version of this feature, remove it
            columnsToBeMapped = columnsToBeMapped.filter((c) => c !== 'timestamp')
            columnsSoFar = columnsToBeMapped.map(
                (e, index): LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined> => {
                    const defaultColumn = defaultColumns.find((d) => d.key === e)
                    if (defaultColumn) {
                        return {
                            ...defaultColumn,
                            render: function render(_, item: EventsTableRowItem) {
                                const { event } = item
                                if (!event) {
                                    if (index === 0) {
                                        return newEventsRender(item, tableWidth)
                                    } else {
                                        return { props: { colSpan: 0 } }
                                    }
                                }
                                if (defaultColumn.render) {
                                    return defaultColumn.render(_, item, index)
                                }
                                return { props: { colSpan: 0 } }
                            },
                        }
                    } else {
                        // If the user has saved their columns for the new data exploration data table, make them work here
                        // This entire file will be removed once we release the new events list feature.
                        const key = e.startsWith('properties.')
                            ? e.substring(11)
                            : e.startsWith('person.properties.')
                            ? e.substring(18)
                            : e
                        return {
                            title: keyMapping['event'][key] ? keyMapping['event'][key].label : key,
                            key: key,
                            render: function render(_, item: EventsTableRowItem) {
                                const { event } = item
                                if (!event) {
                                    if (index === 0) {
                                        return newEventsRender(item, tableWidth)
                                    } else {
                                        return { props: { colSpan: 0 } }
                                    }
                                }
                                if (linkPropertiesToFilters) {
                                    return (
                                        <FilterPropertyLink
                                            className="ph-no-capture "
                                            property={key}
                                            value={event.properties[key] as string}
                                            filters={{ properties }}
                                        />
                                    )
                                }
                                return <Property value={event.properties[key]} />
                            },
                        }
                    }
                }
            )
        }
        columnsSoFar.push({
            title: 'Time',
            key: 'time',
            render: function renderTime(_, { event }: EventsTableRowItem) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                return <TZLabel time={event.timestamp} showSeconds />
            },
        })
        if (showActionsButton) {
            columnsSoFar.push({
                key: 'actions',
                width: 0,
                sticky: true,
                render: function renderActions(_, { event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }

                    const insightUrl = insightUrlForEvent(event)

                    return (
                        <More
                            overlay={
                                <>
                                    {currentTeam && (
                                        <LemonButton
                                            status="stealth"
                                            onClick={() =>
                                                createActionFromEvent(
                                                    currentTeam.id,
                                                    event,
                                                    0,
                                                    currentTeam.data_attributes || []
                                                )
                                            }
                                            fullWidth
                                            data-attr="events-table-create-action"
                                        >
                                            Create action from event
                                        </LemonButton>
                                    )}
                                    {!!event.properties.$session_id && (
                                        <LemonButton
                                            status="stealth"
                                            onClick={() => {
                                                event.properties.$session_id &&
                                                    openSessionPlayer({
                                                        id: event.properties.$session_id,
                                                    })
                                            }}
                                            fullWidth
                                            sideIcon={<IconPlayCircle />}
                                            data-attr="events-table-usage"
                                        >
                                            View recording
                                        </LemonButton>
                                    )}
                                    {insightUrl && (
                                        <LemonButton
                                            to={insightUrl}
                                            status="stealth"
                                            fullWidth
                                            data-attr="events-table-usage"
                                        >
                                            Try out in Insights
                                        </LemonButton>
                                    )}
                                </>
                            }
                        />
                    )
                },
            })
        }
        return fixedColumns ? columnsSoFar.concat(fixedColumns) : columnsSoFar
    }, [selectedColumns, tableWidth])

    const showFirstRow = showEventFilter || showPropertyFilter
    const showSecondRow = showAutoload || showCustomizeColumns || showExport

    const exportColumns = useMemo(() => {
        const columnMapping = {
            url: ['properties.$current_url', 'properties.$screen_name'],
            time: 'timestamp',
            event: 'event',
            source: 'properties.$lib',
            person: ['person.distinct_ids.0', 'person.properties.email'],
        }

        return (selectedColumns === 'DEFAULT' ? defaultColumns.map((e) => e.key || '') : selectedColumns)
            .flatMap((x) => {
                return columnMapping[x] || `properties.${x}`
            })
            .filter((c) => !c.startsWith('custom.'))
    }, [defaultColumns, selectedColumns])

    return (
        <>
            <div className="events" data-attr="events-table">
                {showFirstRow && (
                    <div className="flex space-x-4 mb-4">
                        {showEventFilter && (
                            <LemonEventName
                                value={eventFilter}
                                onChange={(value: string) => {
                                    setEventFilter(value || '')
                                }}
                            />
                        )}
                        {showPropertyFilter && (
                            <PropertyFilters
                                propertyFilters={properties}
                                onChange={setProperties}
                                pageKey={pageKey}
                                style={{ marginBottom: 0, marginTop: 0 }}
                                eventNames={eventFilter ? [eventFilter] : []}
                            />
                        )}
                    </div>
                )}

                {showFirstRow && showSecondRow ? (
                    <div className="my-4">
                        <LemonDivider />
                    </div>
                ) : null}

                {showSecondRow ? (
                    <div className={clsx('flex justify-between items-center mb-4 gap-2 flex-wrap')}>
                        {showAutoload && (
                            <LemonSwitch
                                bordered
                                data-attr="live-events-refresh-toggle"
                                id="autoload-switch"
                                label="Automatically load new events"
                                checked={automaticLoadEnabled}
                                onChange={toggleAutomaticLoad}
                            />
                        )}
                        <div className="flex space-x-2">
                            {showCustomizeColumns && (
                                <LemonTableConfig
                                    immutableColumns={['event', 'person']}
                                    defaultColumns={defaultColumns.map((e) => e.key || '')}
                                />
                            )}
                            {showExport && (
                                <LemonButtonWithDropdown
                                    dropdown={{
                                        sameWidth: false,
                                        closeOnClickInside: false,
                                        overlay: [
                                            <ExportWithConfirmation
                                                key={1}
                                                placement={'topRight'}
                                                onConfirm={() => {
                                                    startDownload(exportColumns)
                                                }}
                                                actor={'events'}
                                                limit={3500}
                                            >
                                                <LemonButton fullWidth={true} status="stealth">
                                                    Export current columns
                                                </LemonButton>
                                            </ExportWithConfirmation>,
                                            <ExportWithConfirmation
                                                key={0}
                                                placement={'bottomRight'}
                                                onConfirm={() => startDownload()}
                                                actor={'events'}
                                                limit={3500}
                                            >
                                                <LemonButton fullWidth={true} status="stealth">
                                                    Export all columns
                                                </LemonButton>
                                            </ExportWithConfirmation>,
                                        ],
                                    }}
                                    type="secondary"
                                    icon={<IconExport />}
                                >
                                    Export
                                </LemonButtonWithDropdown>
                            )}
                        </div>
                    </div>
                ) : null}
                <EventBufferNotice
                    additionalInfo=" - this helps ensure accuracy of insights grouped by unique users"
                    className="mb-4"
                />
                <LemonTable
                    data-attr={dataAttr}
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    key={selectedColumns === 'DEFAULT' ? 'default' : selectedColumns.join('-')}
                    className="ph-no-capture"
                    loadingSkeletonRows={20}
                    emptyState={
                        isLoading ? undefined : properties.some((filter) => Object.keys(filter).length) ||
                          eventFilter ? (
                            `No events matching filters found in the last ${months} months!`
                        ) : (
                            <>
                                This project doesn't have any events. If you haven't integrated PostHog yet,{' '}
                                <Link to="/project/settings">
                                    click here to instrument analytics with PostHog in your product
                                </Link>
                                .
                            </>
                        )
                    }
                    rowKey={(row) =>
                        row.event ? row.event.id + '-' + row.event.event : row.date_break?.toString() || ''
                    }
                    rowClassName={(row) => {
                        return clsx({
                            'event-row': row.event,
                            highlighted: row.event && highlightEvents[row.event.id],
                            'event-row-is-exception': row.event && row.event.event === '$exception',
                            'event-row-date-separator': row.date_break,
                            'event-row-new': row.new_events,
                        })
                    }}
                    expandable={
                        showRowExpanders
                            ? {
                                  expandedRowRender: function renderExpand({ event }) {
                                      return event && <EventDetails event={event} />
                                  },
                                  rowExpandable: ({ event, date_break, new_events }) =>
                                      date_break || new_events ? -1 : !!event,
                                  noIndent: true,
                              }
                            : undefined
                    }
                />
                {hasNext || isLoadingNext ? (
                    <LemonButton
                        type="primary"
                        onClick={fetchNextEvents}
                        loading={isLoadingNext}
                        className="my-8 mx-auto"
                    >
                        Load more events
                    </LemonButton>
                ) : null}
            </div>
            <SessionPlayerModal />
        </>
    )
}
