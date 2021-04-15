import React from 'react'
import { useActions, useValues } from 'kea'
import dayjs from 'dayjs'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { EventDetails } from 'scenes/events/EventDetails'
import { ExportOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { Button, Row, Spin, Tooltip, Col } from 'antd'
import { FilterPropertyLink } from 'lib/components/FilterPropertyLink'
import { Property } from 'lib/components/Property'
import { EventName } from 'scenes/actions/EventName'
import { eventToName, toParams } from 'lib/utils'
import './EventsTable.scss'
import { eventsTableLogic } from './eventsTableLogic'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import relativeTime from 'dayjs/plugin/relativeTime'
import LocalizedFormat from 'dayjs/plugin/localizedFormat'
import { TZLabel } from 'lib/components/TimezoneAware'
import { ResizableTable } from 'lib/components/ResizableTable'

dayjs.extend(LocalizedFormat)
dayjs.extend(relativeTime)

export function EventsTable({ fixedFilters, filtersEnabled = true, pageKey }) {
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
    } = useValues(logic)
    const { fetchNextEvents, prependNewEvents, setEventFilter } = useActions(logic)

    const showLinkToPerson = !fixedFilters?.person_id
    let columns = [
        {
            title: `Event${eventFilter ? ` (${eventFilter})` : ''}`,
            key: 'event',
            rowKey: 'id',
            span: 4,
            render: function renderEvent(item) {
                if (!item.event) {
                    return {
                        children: item.date_break
                            ? item.date_break
                            : newEvents.length === 1
                            ? `There is 1 new event. Click here to load it.`
                            : `There are ${newEvents.length} new events. Click here to load them.`,
                        props: {
                            colSpan: 6,
                            style: {
                                cursor: 'pointer',
                            },
                        },
                    }
                }
                let { event } = item
                return eventToName(event)
            },
        },
        {
            title: 'Person',
            key: 'person',
            ellipsis: true,
            span: 4,
            render: function renderPerson({ event }) {
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
            span: 4,
            render: function renderURL({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                let param = event.properties['$current_url'] ? '$current_url' : '$screen_name'
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
            span: 2,
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
            span: 3,
            render: function renderWhen({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }
                return <TZLabel time={event.timestamp} showSeconds />
            },
        },
        {
            title: 'Usage',
            key: 'usage',
            span: 2,
            render: function renderWhen({ event }) {
                if (!event) {
                    return { props: { colSpan: 0 } }
                }

                if (event.event === '$autocapture') {
                    return <></>
                }

                let eventLink = ''

                if (event.event === '$pageview') {
                    const currentUrl = encodeURIComponent(event.properties.$current_url)
                    eventLink = `/insights?interval=day&display=ActionsLineGraph&actions=%5B%5D&events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22properties%22%3A%5B%7B%22key%22%3A%22%24current_url%22%2C%22value%22%3A%22${currentUrl}%22%2C%22type%22%3A%22event%22%7D%5D%7D%5D`
                } else {
                    const eventTag = encodeURIComponent(event.event)
                    eventLink = `/insights?insight=TRENDS&interval=day&display=ActionsLineGraph&events=%5B%7B%22id%22%3A%22${eventTag}%22%2C%22name%22%3A%22${eventTag}%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%7D%5D&properties=#backTo=Events&backToURL=${window.location.pathname}`
                }

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
    ]

    return (
        <div className="events" data-attr="events-table">
            {filtersEnabled ? <PropertyFilters pageKey={'EventsTable'} /> : null}
            <Row>
                <Col span={pageKey === 'events' ? 22 : 20}>
                    <EventName
                        value={eventFilter}
                        onChange={(value) => {
                            setEventFilter(value || '')
                        }}
                    />
                </Col>
                <Col span={pageKey === 'events' ? 2 : 4} className="text-right">
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
                </Col>
            </Row>
            <div>
                <ResizableTable
                    dataSource={eventsFormatted}
                    loading={isLoading}
                    columns={columns}
                    size="small"
                    className="ph-no-capture"
                    locale={{
                        emptyText: (
                            <span>
                                You don't have any items here! If you haven't integrated PostHog yet,{' '}
                                <Link to="/project/settings">click here to set PostHog up on your app</Link>.
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
