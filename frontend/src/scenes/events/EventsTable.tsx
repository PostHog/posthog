import React, { useMemo } from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { EventDetails } from 'scenes/events/EventDetails'
import { ExportOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { Button, Spin } from 'antd'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { eventToName, toParams } from 'lib/utils'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import relativeTime from 'dayjs/plugin/relativeTime'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import { TZLabel } from 'lib/components/TimezoneAware'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { ViewType } from 'scenes/insights/insightLogic'
import { ResizableColumnType, ResizableTable } from 'lib/components/ResizableTable'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { EventFormattedType } from '~/types'
import { PageHeader } from 'lib/components/PageHeader'
import { TableConfig } from 'lib/components/ResizableTable'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { EventName } from 'scenes/actions/EventName'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)

interface FixedFilters {
    person_id?: string | number
    distinct_ids?: string[]
}

interface EventsTable {
    fixedFilters?: FixedFilters
    filtersEnabled?: boolean
    pageKey?: string
}

export function EventsTable({ fixedFilters, filtersEnabled = true, pageKey }: EventsTable): JSX.Element {
    const logic = eventsTableLogic({ fixedFilters, key: pageKey })
    const {
        properties,
        eventsFormatted,
        orderBy,
        isLoading,
        hasNext,
        isLoadingNext,
        newEvents,
        eventFilter,
        columnConfig,
        columnConfigSaving,
    } = useValues(logic)
    const { propertyNames } = useValues(propertyDefinitionsModel)
    const { fetchNextEvents, prependNewEvents, setColumnConfig, setEventFilter } = useActions(logic)
    const { featureFlags } = useValues(featureFlagLogic)

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
    const defaultColumns: ResizableColumnType<EventFormattedType>[] = useMemo(
        () =>
            [
                {
                    title: `Event${eventFilter ? ` (${eventFilter})` : ''}`,
                    key: 'event',
                    span: 4,
                    render: function render(item: EventFormattedType) {
                        if (!item.event) {
                            return newEventsRender(item, columnConfig === 'DEFAULT' ? 7 : columnConfig.length)
                        }
                        const { event } = item
                        return <PropertyKeyInfo value={eventToName(event)} />
                    },
                    ellipsis: true,
                },
                {
                    title: 'Person',
                    key: 'person',
                    ellipsis: true,
                    span: 4,
                    render: function renderPerson({ event }: EventFormattedType) {
                        if (!event) {
                            return { props: { colSpan: 0 } }
                        }
                        return showLinkToPerson && event.person?.distinct_ids?.length ? (
                            <Link to={`/person/${encodeURIComponent(event.person.distinct_ids[0])}`}>
                                <PersonHeader person={event.person} />
                            </Link>
                        ) : (
                            <PersonHeader person={event.person} />
                        )
                    },
                },
                {
                    title: 'URL / Screen',
                    key: 'url',
                    eventProperties: ['$current_url', '$screen_name'],
                    span: 4,
                    render: function renderURL({ event }: EventFormattedType) {
                        if (!event) {
                            return { props: { colSpan: 0 } }
                        }
                        const param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                        if (filtersEnabled) {
                            return (
                                <FilterPropertyLink
                                    className="ph-no-capture"
                                    property={param}
                                    value={event.properties[param]}
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
                    render: function renderSource({ event }: EventFormattedType) {
                        if (!event) {
                            return { props: { colSpan: 0 } }
                        }
                        if (filtersEnabled) {
                            return (
                                <FilterPropertyLink
                                    property="$lib"
                                    value={event.properties['$lib']}
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
                    render: function renderWhen({ event }: EventFormattedType) {
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
                    render: function renderWhen({ event }: EventFormattedType) {
                        if (!event) {
                            return { props: { colSpan: 0 } }
                        }

                        if (event.event === '$autocapture') {
                            return <></>
                        }

                        let params
                        if (event.event === '$pageview') {
                            params = {
                                insight: ViewType.TRENDS,
                                interval: 'day',
                                display: 'ActionsLineGraph',
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
                                insight: ViewType.TRENDS,
                                interval: 'day',
                                display: 'ActionsLineGraph',
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
                        const encodedParams = toParams(params)
                        const eventLink = `/insights?${encodedParams}`

                        return (
                            <Link
                                to={`${eventLink}#backTo=Events&backToURL=${window.location.pathname}`}
                                data-attr="events-table-usage"
                            >
                                Insights <ExportOutlined />
                            </Link>
                        )
                    },
                },
            ] as ResizableColumnType<EventFormattedType>[],
        [eventFilter, showLinkToPerson, columnConfig]
    )

    const selectedConfigOptions = useMemo(
        () => (columnConfig === 'DEFAULT' ? defaultColumns.map((e) => e.key) : columnConfig),
        [columnConfig]
    )

    const columns = useMemo(
        () =>
            columnConfig === 'DEFAULT'
                ? defaultColumns
                : columnConfig.map(
                      (e: string, index: number): ResizableColumnType<EventFormattedType> =>
                          defaultColumns.find((d) => d.key === e) || {
                              title: keyMapping['event'][e] ? keyMapping['event'][e].label : e,
                              key: e,
                              span: 2,
                              render: function render(item: EventFormattedType) {
                                  const { event } = item
                                  if (!event) {
                                      if (index === 0) {
                                          return newEventsRender(item, columnConfig.length + 1)
                                      } else {
                                          return { props: { colSpan: 0 } }
                                      }
                                  }
                                  if (filtersEnabled) {
                                      return (
                                          <FilterPropertyLink
                                              className="ph-no-capture "
                                              property={e}
                                              value={event.properties[e]}
                                              filters={{ properties }}
                                          />
                                      )
                                  }
                                  return <Property value={event.properties[e]} />
                              },
                              ellipsis: true,
                          }
                  ),
        [columnConfig]
    )

    return (
        <div className="events" data-attr="events-table">
            <PageHeader
                title="Events"
                caption="See events being sent to this project in near real time."
                style={{ marginTop: 0 }}
            />

            <TableConfig
                exportUrl={`/api/event.csv?${toParams({
                    properties,
                    ...(fixedFilters || {}),
                    ...(eventFilter ? { event: eventFilter } : {}),
                    orderBy: [orderBy],
                })}`}
                selectedColumns={selectedConfigOptions}
                availableColumns={featureFlags[FEATURE_FLAGS.EVENT_COLUMN_CONFIG] ? propertyNames : undefined}
                immutableColumns={['event', 'person', 'when']}
                defaultColumns={defaultColumns.map((e) => e.key || '')}
                onColumnUpdate={setColumnConfig}
                saving={columnConfigSaving}
                mainActionComponent={
                    <>
                        <EventName
                            value={eventFilter}
                            onChange={(value: string) => {
                                setEventFilter(value || '')
                            }}
                        />
                        {filtersEnabled ? (
                            <PropertyFilters pageKey={'EventsTable'} style={{ marginBottom: 0 }} />
                        ) : null}
                    </>
                }
            />

            <div>
                <ResizableTable
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    size="small"
                    key={columnConfig === 'DEFAULT' ? 'default' : columnConfig}
                    className="ph-no-capture"
                    scroll={{ x: true }}
                    locale={{
                        emptyText: (
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
                        if (row.event) {
                            return 'event-row ' + (row.event.event === '$exception' && 'event-row-is-exception')
                        }
                        if (row.date_break) {
                            return 'event-day-separator'
                        }
                        if (row.new_events) {
                            return 'event-row-new'
                        }
                        return ''
                    }}
                    expandable={{
                        expandedRowRender: function renderExpand({ event }) {
                            return <EventDetails event={event} />
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
                    <Button type="primary" onClick={fetchNextEvents}>
                        {isLoadingNext ? <Spin /> : 'Load more events'}
                    </Button>
                </div>
            </div>
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}
