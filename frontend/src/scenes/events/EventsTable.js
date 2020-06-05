import React from 'react'
import { useActions, useValues } from 'kea'
import moment from 'moment'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

import { EventDetails } from 'scenes/events/EventDetails'
import { Link } from 'lib/components/Link'
import { Button, Spin, Table, Tooltip } from 'antd'
import { router } from 'kea-router'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'

const eventNameMap = event => {
    if (event.properties.$event_type === 'click') return 'clicked '
    if (event.properties.$event_type === 'change') return 'typed something into '
    if (event.properties.$event_type === 'submit') return 'submitted '
    return event.event
}

export function formatEventName(event) {
    return (
        <>
            {eventNameMap(event)}
            {event.elements.length > 0 && (
                <pre style={{ marginBottom: 0, display: 'inline' }}>&lt;{event.elements[0].tag_name}&gt;</pre>
            )}
            {event.elements.length > 0 && event.elements[0].text && ' with text "' + event.elements[0].text + '"'}
        </>
    )
}

export function EventsTable({ fixedFilters, filtersEnabled = true, logic, isLiveActions }) {
    const { properties, eventsFormatted, isLoading, hasNext, isLoadingNext, newEvents } = useValues(logic)
    const { fetchNextEvents, prependNewEvents } = useActions(logic)
    const {
        location: { search },
    } = useValues(router)

    const showLinkToPerson = !fixedFilters?.person_id
    let columns = [
        {
            title: 'Event',
            key: 'event',
            render: function renderEvent(item) {
                if (!item.event)
                    return {
                        children: item.date_break
                            ? item.date_break
                            : `There are ${newEvents.length} new events. Click here to load them`,
                        props: {
                            colSpan: isLiveActions ? 6 : 5,
                            style: {
                                cursor: 'pointer',
                            },
                        },
                    }
                let { event } = item
                return formatEventName(event)
            },
        },
        {
            title: 'Person',
            key: 'person',
            render: function renderPerson({ event }) {
                if (!event) return { props: { colSpan: 0 } }
                return showLinkToPerson ? (
                    <Link to={`/person/${encodeURIComponent(event.distinct_id)}${search}`} className="ph-no-capture">
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
                if (!event) return { props: { colSpan: 0 } }
                let param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
                if (filtersEnabled)
                    return (
                        <FilterPropertyLink property={param} value={event.properties[param]} filters={{ properties }} />
                    )
                return <Property value={event.properties[param]} />
            },
            ellipsis: true,
        },
        {
            title: 'Source',
            key: 'source',
            render: function renderSource({ event }) {
                if (!event) return { props: { colSpan: 0 } }
                if (filtersEnabled)
                    return (
                        <FilterPropertyLink property="$lib" value={event.properties['$lib']} filters={{ properties }} />
                    )
                return <Property value={event.properties['$lib']} />
            },
        },
        {
            title: 'When',
            key: 'when',
            render: function renderWhen({ event }) {
                if (!event) return { props: { colSpan: 0 } }
                return <Tooltip title={event.timestamp}>{moment(event.timestamp).fromNow()}</Tooltip>
            },
        },
    ]
    if (isLiveActions)
        columns.splice(0, 0, {
            title: 'Action',
            key: 'action',
            render: function renderAction(item) {
                if (!item.event) return { props: { colSpan: 0 } }
                return <Link to={'/action/' + item.event.actionId}>{item.event.actionName}</Link>
            },
        })

    return (
        <div className="events" data-attr="events-table">
            <h1 className="page-header">Events</h1>
            {filtersEnabled ? <PropertyFilters pageKey="EventsTable" /> : null}
            <Table
                dataSource={eventsFormatted}
                loading={isLoading}
                columns={columns}
                size="small"
                locale={{
                    emptyText: (
                        <span>
                            You don't have any items here. If you haven't integrated PostHog yet,{' '}
                            <Link to="/setup">click here to set PostHog up on your app</Link>
                        </span>
                    ),
                }}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowKey={row => (row.event ? row.event.id + '-' + row.event.actionId : row.date_break)}
                rowClassName={row => {
                    if (row.event) return 'event-row'
                    if (row.date_break) return 'event-day-separator'
                    if (row.new_events) return 'event-row-new'
                }}
                expandable={{
                    expandedRowRender: function renderExpand({ event }) {
                        return <EventDetails event={event} />
                    },
                    rowExpandable: ({ event }) => event,
                    expandRowByClick: true,
                }}
                onRow={row => ({
                    onClick: () => {
                        if (row.new_events) prependNewEvents(newEvents)
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
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}
