import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import { EventDetails } from 'scenes/events/EventDetails'
import { DownloadOutlined, ExportOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { Button, Col, Row } from 'antd'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { autoCaptureEventToDescription } from 'lib/utils'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { TZLabel } from 'lib/components/TimezoneAware'
import { keyMapping, PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TableConfig } from 'lib/components/ResizableTable'
import {
    ActionType,
    AnyPropertyFilter,
    ChartDisplayType,
    EventsTableRowItem,
    EventType,
    FilterType,
    InsightType,
} from '~/types'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { EventName } from 'scenes/actions/EventName'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { Tooltip } from 'lib/components/Tooltip'
import { LabelledSwitch } from 'scenes/events/LabelledSwitch'
import clsx from 'clsx'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'
import { EventsTab } from 'scenes/events/EventsTabs'
import { urls } from 'scenes/urls'
import { EventPageHeader } from './EventPageHeader'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/components/LemonTable'
import { TableCellRepresentation } from 'lib/components/LemonTable/types'
import { IconSync } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'

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
    pageKey,
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
                        onClick={() => prependNewEvents(newEvents)}
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
                title: `Event${eventFilter ? ` (${eventFilter})` : ''}`,
                key: 'event',
                render: function render(item: EventsTableRowItem) {
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
                render: function renderURL({ event }: EventsTableRowItem) {
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
                render: function renderSource({ event }: EventsTableRowItem) {
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
            {
                title: 'When',
                key: 'when',
                render: function renderWhen({ event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }
                    return <TZLabel time={event.timestamp} showSeconds />
                },
            },
            {
                title: 'Usage',
                key: 'usage',
                render: function renderUsage({ event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }

                    if (event.event === '$autocapture') {
                        return <></>
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
                    const eventLink = urls.insightNew(params)

                    return (
                        <Link to={eventLink} data-attr="events-table-usage">
                            Insights <ExportOutlined />
                        </Link>
                    )
                },
            },
        ] as LemonTableColumns<EventsTableRowItem>
        if (!hidePersonColumn) {
            _localColumns.splice(1, 0, personColumn)
        }
        return _localColumns
    }, [eventFilter, tableWidth])

    const columns = useMemo(
        () =>
            selectedColumns === 'DEFAULT'
                ? defaultColumns
                : selectedColumns.map(
                      (
                          e: string,
                          index: number
                      ): LemonTableColumn<EventsTableRowItem, keyof EventsTableRowItem | undefined> =>
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
                  ),

        [selectedColumns]
    )

    return (
        <div data-attr="manage-events-table">
            <div className="events" data-attr="events-table">
                <EventPageHeader activeTab={EventsTab.Events} hideTabs={!sceneIsEventsPage} />

                <Row gutter={[16, 16]}>
                    <Col xs={24} sm={12}>
                        <EventName
                            value={eventFilter}
                            onChange={(value: string) => {
                                setEventFilter(value || '')
                            }}
                        />
                    </Col>
                    <Col span={24}>
                        {filtersEnabled ? (
                            <PropertyFilters pageKey={'EventsTable'} style={{ marginBottom: 0 }} />
                        ) : null}
                    </Col>
                </Row>

                <Row gutter={[16, 16]} justify="end">
                    <Col flex="1">
                        <LabelledSwitch
                            label={'Automatically load new events'}
                            enabled={automaticLoadEnabled}
                            onToggle={toggleAutomaticLoad}
                            align="right"
                        />
                    </Col>
                    <Col flex="0">
                        {exportUrl && (
                            <Tooltip title="Export up to 10,000 latest events." placement="left">
                                <Button icon={<DownloadOutlined />} onClick={startDownload}>
                                    Export events
                                </Button>
                            </Tooltip>
                        )}
                    </Col>
                    <Col flex="0">
                        <TableConfig
                            availableColumns={propertyNames}
                            immutableColumns={['event', 'person', 'when']}
                            defaultColumns={defaultColumns.map((e) => e.key || '')}
                        />
                    </Col>
                </Row>

                <LemonTable
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    size="small"
                    key={selectedColumns === 'DEFAULT' ? 'default' : selectedColumns.join('-')}
                    className="ph-no-capture"
                    emptyState={
                        isLoading ? (
                            <span>&nbsp;</span>
                        ) : (
                            <span>
                                You don't have any items here! If you haven't integrated PostHog yet,{' '}
                                <Link to="/project/settings">click here to set PostHog up on your app</Link>.
                            </span>
                        )
                    }
                    rowKey={(row) =>
                        row.event ? row.event.id + '-' + row.event.event : row.date_break?.toString() || ''
                    }
                    rowClassName={(row) => {
                        return clsx({
                            'event-row': row.event,
                            highlighted: row.event && highlightEvents[(row.event as EventType).id],
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
                <div
                    style={{
                        visibility: hasNext || isLoadingNext ? 'visible' : 'hidden',
                        margin: '2rem auto 5rem',
                        textAlign: 'center',
                    }}
                >
                    <Button
                        type="primary"
                        onClick={fetchNextEvents}
                        disabled={isLoadingNext}
                        style={{ display: 'inline-flex', alignItems: 'center' }}
                    >
                        {isLoadingNext ? <Spinner size="sm" /> : 'Load more events'}
                    </Button>
                </div>
                <div style={{ marginTop: '5rem' }} />
            </div>
        </div>
    )
}
