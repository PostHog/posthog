import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { EventDetails } from 'scenes/events/EventDetails'
import { ExportOutlined, SearchOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { Button, Spin, Table, Tooltip } from 'antd'
import { router } from 'kea-router'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { EventName } from 'scenes/actions/EventName'
import { eventToName, toParams } from 'lib/utils'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { hot } from 'react-hot-loader/root'

export const EventsTable = hot(_EventsTable)
function _EventsTable({ fixedFilters, filtersEnabled = true }) {
    const logic = eventsTableLogic({ fixedFilters })
    const {
        properties,
        eventsFormatted,
        orderBy,
        isLoading,
        hasNext,
        isLoadingNext,
        newEvents,
        eventFilter,
    } = useValues(logic)
    const { fetchNextEvents, prependNewEvents, setEventFilter } = useActions(logic)
    const {
        location: { search },
    } = useValues(router)

    const showLinkToPerson = !fixedFilters?.person_id
    let columns = [
        {
            title: `Event${eventFilter ? ` (${eventFilter})` : ''}`,
            key: 'event',
            render: function renderEvent(item) {
                if (!item.event) {
                    return {
                        children: item.date_break
                            ? item.date_break
                            : newEvents.length === 1
                            ? `There is 1 new event. Click here to load it.`
                            : `There are ${newEvents.length} new events. Click here to load them.`,
                        props: {
                            colSpan: 5,
                            style: {
                                cursor: 'pointer',
                            },
                        },
                    }
                }
                let { event } = item
                return eventToName(event)
            },
            filterIcon: function RenderFilterIcon() {
                return (
                    <SearchOutlined
                        style={{ color: eventFilter && 'var(--primary)' }}
                        data-attr="event-filter-trigger"
                    />
                )
            },
            filterDropdown: function RenderFilter({ confirm }) {
                return (
                    <div style={{ padding: '1rem' }}>
                        <Button
                            style={{ float: 'right', marginTop: -6, marginBottom: 8 }}
                            onClick={() => {
                                confirm()
                                setEventFilter(false)
                            }}
                            type="primary"
                            disabled={!eventFilter}
                        >
                            Reset
                        </Button>
                        Filter by event
                        <EventName
                            value={eventFilter}
                            onChange={(value) => {
                                confirm()
                                setEventFilter(value)
                            }}
                        />
                    </div>
                )
            },
        },
        {
            title: 'Person',
            key: 'person',
            ellipsis: true,
            render: function renderPerson({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                return showLinkToPerson ? (
                    <Link
                        to={`/person/${encodeURIComponent(event.distinct_id)}${search}`}
                        className={'ph-no-capture ' + rrwebBlockClass}
                    >
                        {event.person}
                    </Link>
                ) : (
                    event.person
                )
            },
        },
        {
            title: 'URL / Screen',
            key: 'url',
            render: function renderURL({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                let param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                if (filtersEnabled) {
                    return (
                        <FilterPropertyLink
                            className={'ph-no-capture ' + rrwebBlockClass}
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
            render: function renderSource({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                if (filtersEnabled) {
                    return (
                        <FilterPropertyLink property="$lib" value={event.properties['$lib']} filters={{ properties }} />
                    )
                }
                return <Property value={event.properties['$lib']} />
            },
        },
        {
            title: 'When',
            key: 'when',
            render: function renderWhen({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                return (
                    <Tooltip title={moment(event.timestamp).format('LLL')}>{moment(event.timestamp).fromNow()}</Tooltip>
                )
            },
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            {filtersEnabled ? <PropertyFilters pageKey={'EventsTable'} /> : null}
            <Tooltip title="Up to 100,000 latest events.">
                <Button
                    type="default"
                    icon={<ExportOutlined />}
                    href={`/api/event.csv?${toParams({
                        properties,
                        ...(fixedFilters || {}),
                        ...(eventFilter ? { event: eventFilter } : {}),
                        orderBy: [orderBy],
                    })}`}
                    style={{ marginBottom: '1rem' }}
                >
                    Export
                </Button>
            </Tooltip>
            <div>
                <Table
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    size="small"
                    className={rrwebBlockClass + ' ph-no-capture'}
                    locale={{
                        emptyText: (
                            <span>
                                You don't have any items here! If you haven't integrated PostHog yet,{' '}
                                <Link to="/project">click here to set PostHog up on your app</Link>.
                            </span>
                        ),
                    }}
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    rowKey={(row) => (row.event ? row.event.id + '-' + row.event.actionId : row.date_break)}
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
                    }}
                    expandable={{
                        expandedRowRender: function renderExpand({ event }) {
                            return <EventDetails event={event} />
                        },
                        rowExpandable: ({ event }) => event,
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
