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
import { ResizableColumnType, ResizableTable, TableConfig } from 'lib/components/ResizableTable'
import { ActionType, ChartDisplayType, EventsTableRowItem, EventType, FilterType, InsightType } from '~/types'
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

export interface FixedFilters {
    action_id?: ActionType['id']
    person_id?: string | number
    distinct_ids?: string[]
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
    const { fetchNextEvents, prependNewEvents, setEventFilter, toggleAutomaticLoad } = useActions(logic)

    const showLinkToPerson = !fixedFilters?.person_id
    const newEventsRender = (item: Record<string, any>, colSpan: number): Record<string, any> => {
        return {
            children: item.date_break
                ? item.date_break
                : newEvents.length === 1
                ? `There is 1 new event. Click here to load it.`
                : `There are ${newEvents.length || ''} new events. Click here to load them.`,
            props: {
                colSpan,
                style: {
                    cursor: 'pointer',
                },
            },
        }
    }
    const personColumn = {
        title: 'Person',
        key: 'person',
        ellipsis: true,
        span: 4,
        render: function renderPerson({ event }: EventsTableRowItem) {
            if (!event) {
                return { props: { colSpan: 0 } }
            }
            return showLinkToPerson && event.person?.distinct_ids?.length ? (
                <Link to={urls.person(encodeURIComponent(event.person.distinct_ids[0]))}>
                    <PersonHeader withIcon person={event.person} />
                </Link>
            ) : (
                <PersonHeader withIcon person={event.person} />
            )
        },
    }

    const defaultColumns: ResizableColumnType<EventsTableRowItem>[] = useMemo(() => {
        const _localColumns = [
            {
                title: `Event${eventFilter ? ` (${eventFilter})` : ''}`,
                key: 'event',
                span: 4,
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
                eventProperties: ['$current_url', '$screen_name'],
                span: 4,
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
                eventProperties: ['$lib'],
                span: 2,
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
                span: 3,
                render: function renderWhen({ event }: EventsTableRowItem) {
                    if (!event) {
                        return { props: { colSpan: 0 } }
                    }
                    return <TZLabel time={event.timestamp} showSeconds />
                },
                ellipsis: true,
            },
            {
                title: 'Usage',
                key: 'usage',
                span: 2,
                render: function renderWhen({ event }: EventsTableRowItem) {
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
        ] as ResizableColumnType<EventsTableRowItem>[]
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
                      (e: string, index: number): ResizableColumnType<EventsTableRowItem> =>
                          defaultColumns.find((d) => d.key === e) || {
                              title: keyMapping['event'][e] ? keyMapping['event'][e].label : e,
                              key: e,
                              span: 2,
                              render: function render(item: EventsTableRowItem) {
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
                              ellipsis: true,
                          }
                  ),

        [selectedColumns]
    )

    return (
        <div data-attr="manage-events-table" style={sceneIsEventsPage ? { paddingTop: 16 } : undefined}>
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
                                <Button icon={<DownloadOutlined />} href={exportUrl}>
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

                <div>
                    <ResizableTable
                        dataSource={eventsFormatted}
                        loading={isLoading}
                        columns={columns}
                        size="small"
                        key={selectedColumns === 'DEFAULT' ? 'default' : selectedColumns.join('-')}
                        className="ph-no-capture"
                        locale={{
                            emptyText: isLoading ? (
                                <span>&nbsp;</span>
                            ) : (
                                <span>
                                    You don't have any items here! If you haven't integrated PostHog yet,{' '}
                                    <Link to="/project/settings">click here to set PostHog up on your app</Link>.
                                </span>
                            ),
                        }}
                        pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                        rowKey={(row) =>
                            row.event ? row.event.id + '-' + row.event.event : row.date_break?.toString() || ''
                        }
                        rowClassName={(row) => {
                            return clsx({
                                'event-row': row.event,
                                'highlight-new-row': row.event && highlightEvents[(row.event as EventType).id],
                                'event-row-is-exception': row.event && row.event.event === '$exception',
                                'event-day-separator': row.date_break,
                                'event-row-new': row.new_events,
                            })
                        }}
                        expandable={{
                            expandedRowRender: function renderExpand({ event }) {
                                return event && <EventDetails event={event} />
                            },
                            rowExpandable: ({ event }) => !!event,
                            expandRowByClick: true,
                        }}
                        onRow={(row) => ({
                            onClick: () => {
                                if (row.new_events) {
                                    prependNewEvents(newEvents)
                                }
                            },
                        })}
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
                </div>
                <div style={{ marginTop: '5rem' }} />
            </div>
        </div>
    )
}
