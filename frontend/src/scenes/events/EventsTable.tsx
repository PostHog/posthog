import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { EventDetails } from 'scenes/events/EventDetails'
import { DownloadOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { Button } from 'antd'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { autoCaptureEventToDescription } from 'lib/utils'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { TZLabel } from 'lib/components/TimezoneAware'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TableConfig } from 'lib/components/ResizableTable'
import { ActionType, AnyPropertyFilter, ChartDisplayType, EventsTableRowItem, FilterType, InsightType } from '~/types'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { EventName } from 'scenes/actions/EventName'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { Tooltip } from 'lib/components/Tooltip'
import clsx from 'clsx'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { EventsTab } from 'scenes/events/EventsTabs'
import { urls } from 'scenes/urls'
import { EventPageHeader } from './EventPageHeader'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { TableCellRepresentation } from 'lib/components/LemonTable/types'
import { IconSync } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { More } from 'lib/components/LemonButton/More'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'

export interface FixedFilters {
    action_id?: ActionType['id']
    person_id?: string | number
    distinct_ids?: string[]
    properties?: AnyPropertyFilter[]
}

interface EventsTable {
    fixedFilters?: FixedFilters
    filtersEnabled?: boolean
    pageKey?: string
    hidePersonColumn?: boolean
    sceneUrl?: string
}

export function EventsTable({
    fixedFilters,
    filtersEnabled = true,
    pageKey = 'EventsTable',
    hidePersonColumn,
    sceneUrl,
}: EventsTable = {}): JSX.Element {
    const logic = eventsTableLogic({ fixedFilters, key: pageKey, sceneUrl: sceneUrl || urls.events() })
    const {
        properties,
        eventsFormatted,
        isLoading,
        hasNext,
        isLoadingNext,
        newEvents,
        eventFilter,
        automaticLoadEnabled,
        exportUrl,
        highlightEvents,
        sceneIsEventsPage,
    } = useValues(logic)
    const { tableWidth, selectedColumns } = useValues(tableConfigLogic)
    const { propertyNames } = useValues(propertyDefinitionsModel)
    const { fetchNextEvents, prependNewEvents, setEventFilter, toggleAutomaticLoad, startDownload } = useActions(logic)
    const { filters } = useValues(propertyFilterLogic({ pageKey }))

    const showLinkToPerson = !fixedFilters?.person_id

    const newEventsRender = (
        { date_break, new_events }: EventsTableRowItem,
        colSpan: number
    ): TableCellRepresentation => {
        return {
            children:
                date_break ||
                (new_events ? (
                    <LemonButton
                        icon={<IconSync />}
                        style={{ borderRadius: 0 }}
                        onClick={() => prependNewEvents()}
                        center
                        fullWidth
                    >
                        {newEvents.length === 1
                            ? `There is 1 new event. Click here to load it`
                            : `There are ${newEvents.length || ''} new events. Click here to load them`}
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
                    <PersonHeader withIcon person={event.person} />
                </Link>
            ) : (
                <PersonHeader withIcon person={event.person} />
            )
        },
    }

    const defaultColumns = useMemo<LemonTableColumns<EventsTableRowItem>>(() => {
        const _localColumns = [
            {
                title: 'Event',
                key: 'event',
                width: '16rem',
                render: function render(_, item: EventsTableRowItem) {
                    if (!item.event) {
                        return newEventsRender(item, tableWidth)
                    }
                    const { event } = item
                    return <PropertyKeyInfo value={autoCaptureEventToDescription(event)} />
                },
                ellipsis: true,
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
                    if (filtersEnabled) {
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
                ellipsis: true,
            },
            {
                title: 'Source',
                key: 'source',
                render: function renderSource(_, { event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }
                    if (filtersEnabled) {
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
        ] as LemonTableColumns<EventsTableRowItem>
        if (!hidePersonColumn) {
            _localColumns.splice(1, 0, personColumn)
        }
        return _localColumns
    }, [tableWidth])

    const columns = useMemo(() => {
        const columnsSoFar =
            selectedColumns === 'DEFAULT'
                ? defaultColumns
                : selectedColumns.map(
                      (e, index): LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined> =>
                          defaultColumns.find((d) => d.key === e) || {
                              title: keyMapping['event'][e] ? keyMapping['event'][e].label : e,
                              key: e,
                              render: function render(_, item: EventsTableRowItem) {
                                  const { event } = item
                                  if (!event) {
                                      if (index === 0) {
                                          return newEventsRender(item, tableWidth)
                                      } else {
                                          return { props: { colSpan: 0 } }
                                      }
                                  }
                                  if (filtersEnabled) {
                                      return (
                                          <FilterPropertyLink
                                              className="ph-no-capture "
                                              property={e}
                                              value={event.properties[e] as string}
                                              filters={{ properties }}
                                          />
                                      )
                                  }
                                  return <Property value={event.properties[e]} />
                              },
                          }
                  )
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
        columnsSoFar.push({
            key: 'actions',
            width: 0,
            render: function renderActions(_, { event }: EventsTableRowItem) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }

                if (event.event === '$autocapture') {
                    return null
                }

                let params: Partial<FilterType>
                if (event.event === '$pageview') {
                    params = {
                        insight: InsightType.TRENDS,
                        interval: 'day',
                        display: ChartDisplayType.ActionsLineGraphLinear,
                        actions: [],
                        events: [
                            {
                                id: '$pageview',
                                name: '$pageview',
                                type: 'events',
                                order: 0,
                                properties: [
                                    {
                                        key: '$current_url',
                                        value: event.properties.$current_url,
                                        type: 'event',
                                    },
                                ],
                            },
                        ],
                    }
                } else {
                    params = {
                        insight: InsightType.TRENDS,
                        interval: 'day',
                        display: ChartDisplayType.ActionsLineGraphLinear,
                        actions: [],
                        events: [
                            {
                                id: event.event,
                                name: event.event,
                                type: 'events',
                                order: 0,
                                properties: [],
                            },
                        ],
                    }
                }

                return (
                    <More
                        overlay={
                            <LemonButton
                                type="stealth"
                                to={urls.insightNew(params)}
                                fullWidth
                                data-attr="events-table-usage"
                            >
                                Try out in Insights
                            </LemonButton>
                        }
                    />
                )
            },
        })
        return columnsSoFar
    }, [selectedColumns])

    return (
        <div data-attr="manage-events-table">
            <div className="events" data-attr="events-table">
                <EventPageHeader activeTab={EventsTab.Events} hideTabs={!sceneIsEventsPage} />
                <div
                    className="mb"
                    style={{
                        display: 'flex',
                        gap: '0.75rem',
                        flexWrap: 'wrap',
                        justifyContent: 'space-between',
                        alignItems: 'start',
                    }}
                >
                    <div style={{ display: 'flex', gap: '0.75rem', flexDirection: 'column', flexGrow: 1 }}>
                        <EventName
                            value={eventFilter}
                            onChange={(value: string) => {
                                setEventFilter(value || '')
                            }}
                        />
                        {filtersEnabled && <PropertyFilters pageKey={pageKey} style={{ marginBottom: 0 }} />}
                    </div>

                    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '0.75rem' }}>
                        <LemonSwitch
                            id="autoload-switch"
                            label="Automatically load new events"
                            checked={automaticLoadEnabled}
                            onChange={toggleAutomaticLoad}
                        />
                        <TableConfig
                            availableColumns={propertyNames}
                            immutableColumns={['event', 'person']}
                            defaultColumns={defaultColumns.map((e) => e.key || '')}
                        />
                        {exportUrl && (
                            <Tooltip title="Export up to 10,000 latest events." placement="left">
                                <Button icon={<DownloadOutlined />} onClick={startDownload}>
                                    Export events
                                </Button>
                            </Tooltip>
                        )}
                    </div>
                </div>

                <LemonTable
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    key={selectedColumns === 'DEFAULT' ? 'default' : selectedColumns.join('-')}
                    className="ph-no-capture"
                    emptyState={
                        isLoading ? undefined : Object.keys(filters).length || eventFilter ? (
                            'No events matching filters!'
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
                    expandable={{
                        expandedRowRender: function renderExpand({ event }) {
                            return event && <EventDetails event={event} />
                        },
                        rowExpandable: ({ event, date_break, new_events }) => (date_break || new_events ? -1 : !!event),
                    }}
                />
                <Button
                    type="primary"
                    onClick={fetchNextEvents}
                    loading={isLoadingNext}
                    style={{
                        display: hasNext || isLoadingNext ? 'block' : 'none',
                        margin: '2rem auto 1rem',
                    }}
                >
                    Load more events
                </Button>
            </div>
        </div>
    )
}
