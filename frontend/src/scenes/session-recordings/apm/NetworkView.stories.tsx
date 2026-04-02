import './NetworkView.scss'

import { Meta } from '@storybook/react'
import { useCallback, useRef, useState } from 'react'

import { LemonTable } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { humanFriendlyMilliseconds } from 'lib/utils'
import { initiatorTypeToColor } from 'scenes/session-recordings/apm/performance-event-utils'
import { MethodTag, StatusTag } from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'

import { PerformanceEvent } from '~/types'

const meta: Meta = {
    title: 'Scenes/Session Recordings/NetworkView',
    parameters: {
        layout: 'padded',
    },
}
export default meta

const MOCK_NETWORK_DATA: PerformanceEvent[] = [
    {
        uuid: '1',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'navigation',
        initiator_type: 'navigation',
        name: 'https://app.posthog.com/project/1/dashboard',
        start_time: 0,
        response_end: 1200,
        load_event_end: 2500,
        domain_lookup_start: 0,
        domain_lookup_end: 45,
        connect_start: 45,
        connect_end: 120,
        request_start: 120,
        response_start: 350,
        response_status: 200,
    },
    {
        uuid: '2',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'script',
        name: 'https://app.posthog.com/static/js/main.a1b2c3d4.chunk.js',
        start_time: 150,
        response_end: 800,
        response_status: 200,
    },
    {
        uuid: '3',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'css',
        name: 'https://app.posthog.com/static/css/styles.e5f6g7h8.css',
        start_time: 160,
        response_end: 450,
        response_status: 200,
    },
    {
        uuid: '4',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'fetch',
        name: 'https://us.i.posthog.com/api/projects/1/insights/?short_id=abc123&refresh=true&client_query_id=xyz789',
        start_time: 900,
        response_end: 1800,
        request_start: 910,
        response_start: 1600,
        response_status: 200,
    },
    {
        uuid: '5',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'fetch',
        name: 'https://us.i.posthog.com/api/projects/1/insights/?short_id=def456&refresh=true&client_query_id=uvw321',
        start_time: 920,
        response_end: 2100,
        request_start: 930,
        response_start: 1900,
        response_status: 200,
    },
    {
        uuid: '6',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'xmlhttprequest',
        name: 'https://us.i.posthog.com/api/projects/1/session_recordings?limit=20&offset=0',
        start_time: 950,
        response_end: 1600,
        response_status: 200,
    },
    {
        uuid: '7',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'img',
        name: 'https://app.posthog.com/static/media/logo.svg',
        start_time: 500,
        response_end: 620,
        response_status: 200,
    },
    {
        uuid: '8',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'fetch',
        name: 'https://us.i.posthog.com/decide/?v=3&ip=1&ver=1.57.2',
        start_time: 200,
        response_end: 550,
        response_status: 200,
    },
    {
        uuid: '9',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'script',
        name: 'https://app.posthog.com/static/js/vendor.m3n4o5p6.chunk.js',
        start_time: 170,
        response_end: 950,
        response_status: 200,
    },
    {
        uuid: '10',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'beacon',
        name: 'https://us.i.posthog.com/e/?ip=1&ver=1.57.2',
        start_time: 2200,
        response_end: 2350,
        response_status: 200,
    },
    {
        uuid: '11',
        timestamp: Date.now(),
        distinct_id: 'u',
        session_id: 's',
        window_id: 'w',
        pageview_id: 'p',
        current_url: '',
        entry_type: 'resource',
        initiator_type: 'fetch',
        name: 'https://us.i.posthog.com/api/projects/1/insights/trend/?events=%5B%7B%22id%22%3A%22%24pageview%22%2C%22name%22%3A%22%24pageview%22%2C%22type%22%3A%22events%22%2C%22order%22%3A0%2C%22math%22%3A%22total%22%7D%5D&properties=%5B%7B%22key%22%3A%22%24browser%22%2C%22value%22%3A%22Chrome%22%2C%22operator%22%3A%22exact%22%2C%22type%22%3A%22person%22%7D%5D&filter_test_accounts=true&date_from=-30d&interval=day&refresh=true&client_query_id=abc123def456ghi789jkl012mno345pqr678',
        start_time: 1000,
        response_end: 2000,
        request_start: 1010,
        response_start: 1800,
        response_status: 200,
    },
] as PerformanceEvent[]

const FIXED_COLUMNS_WIDTH = 128 + 86 + 100

function useColumnResize(
    initialWidth: number,
    containerRef: React.RefObject<HTMLDivElement | null>
): [number, (e: React.MouseEvent) => void] {
    const [width, setWidth] = useState(initialWidth)
    const widthRef = useRef(initialWidth)
    widthRef.current = width

    const onMouseDown = useCallback(
        (e: React.MouseEvent) => {
            if (e.button !== 0) {
                return
            }
            e.preventDefault()
            const startX = e.pageX
            const startWidth = widthRef.current
            const containerWidth = containerRef.current?.offsetWidth ?? 800
            const maxWidth = Math.max(200, containerWidth - FIXED_COLUMNS_WIDTH)

            const onMouseMove = (moveEvent: MouseEvent): void => {
                const delta = moveEvent.pageX - startX
                setWidth(Math.max(100, Math.min(maxWidth, startWidth + delta)))
            }
            const onMouseUp = (): void => {
                document.removeEventListener('mousemove', onMouseMove)
                document.removeEventListener('mouseup', onMouseUp)
                document.body.style.cursor = ''
                document.body.style.userSelect = ''
            }

            document.addEventListener('mousemove', onMouseMove)
            document.addEventListener('mouseup', onMouseUp)
            document.body.style.cursor = 'col-resize'
            document.body.style.userSelect = 'none'
        },
        [containerRef]
    )

    return [width, onMouseDown]
}

function SimpleURL({ name, entryType }: { name: string | undefined; entryType: string | undefined }): JSX.Element {
    if (!name || !name.trim().length) {
        return <>(empty string)</>
    }
    try {
        const url = new URL(name)
        return (
            <Tooltip
                title={
                    <div className="flex flex-col deprecated-space-y-2">
                        <div>
                            {url.protocol}://{url.hostname}
                            {url.port.length ? `:${url.port}` : null}
                        </div>
                        <div>{url.pathname}</div>
                        {url.search.length ? <div>{url.search}</div> : null}
                        {url.hash.length ? <div>{url.hash}</div> : null}
                    </div>
                }
            >
                <span className="whitespace-nowrap">
                    {entryType === 'navigation' ? url.hostname : null}
                    {url.pathname}
                    {url.search}
                    {url.hash}
                </span>
            </Tooltip>
        )
    } catch {
        return <span>{name}</span>
    }
}

function MockNetworkBar({ item }: { item: PerformanceEvent }): JSX.Element {
    const rangeStart = MOCK_NETWORK_DATA[0]?.start_time ?? 0
    const lastItem = MOCK_NETWORK_DATA[MOCK_NETWORK_DATA.length - 1]
    const rangeEnd = (lastItem?.load_event_end ?? lastItem?.response_end ?? 1) as number
    const totalDuration = rangeEnd - rangeStart
    const itemStart = (item.start_time ?? 0) - rangeStart
    const itemEnd = ((item.load_event_end ?? item.response_end ?? 0) as number) - rangeStart
    return (
        <div
            className="relative h-5"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={{
                backgroundColor: initiatorTypeToColor(item.initiator_type || 'other'),
                width: `${Math.max(0.5, ((itemEnd - itemStart) / totalDuration) * 100)}%`,
                minWidth: 2,
                left: `${Math.max(0, (itemStart / totalDuration) * 100)}%`,
            }}
        />
    )
}

function MockDuration({ item }: { item: PerformanceEvent }): JSX.Element {
    const start = item.start_time
    const end = (item.load_event_end ?? item.response_end) as number | undefined
    if (start !== undefined && end !== undefined) {
        return <div className="text-right">{humanFriendlyMilliseconds(end - start)}</div>
    }
    return <div className="text-right" />
}

function NetworkStatus({ item }: { item: PerformanceEvent }): JSX.Element | null {
    return (
        <div className="flex flex-row justify-around">
            <MethodTag item={item} label={false} />
            <StatusTag item={item} detailed={false} />
        </div>
    )
}

export function Default(): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [urlColumnWidth, onUrlHeaderMouseDown] = useColumnResize(250, containerRef)

    return (
        <div className="NetworkView overflow-y-auto py-2 px-4" style={{ maxWidth: 800 }}>
            <div ref={containerRef} className="relative deprecated-space-y-1 px-0">
                <div
                    className="NetworkView__column-resize absolute top-0 bottom-0 z-10 cursor-col-resize"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: urlColumnWidth }}
                    onMouseDown={onUrlHeaderMouseDown}
                />
                <LemonTable
                    className="NetworkView__table"
                    size="small"
                    dataSource={MOCK_NETWORK_DATA}
                    columns={[
                        {
                            title: 'URL',
                            key: 'url',
                            dataIndex: 'name',
                            width: urlColumnWidth,
                            render: function RenderUrl(_, item) {
                                return <SimpleURL name={item.name} entryType={item.entry_type} />
                            },
                        },
                        {
                            title: 'Timings',
                            key: 'timings',
                            render: function RenderTimings(_, item) {
                                return <MockNetworkBar item={item} />
                            },
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            width: 128,
                            align: 'center',
                            render: function RenderStatus(_, item) {
                                return <NetworkStatus item={item} />
                            },
                        },
                        {
                            title: 'Duration',
                            key: 'duration',
                            width: 86,
                            align: 'right',
                            render: function RenderDuration(_, item) {
                                return <MockDuration item={item} />
                            },
                        },
                    ]}
                />
            </div>
        </div>
    )
}
