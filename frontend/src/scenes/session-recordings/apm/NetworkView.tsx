import './NetworkView.scss'

import { BindLogic, useActions, useValues } from 'kea'
import { useCallback, useRef, useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonTable, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import AssetProportions from 'scenes/session-recordings/apm/components/AssetProportions'
import { PerformanceCardRow } from 'scenes/session-recordings/apm/components/PerformanceCard'
import { MethodTag, StatusTag } from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'
import { NetworkBar } from 'scenes/session-recordings/apm/waterfall/NetworkBar'

import { PerformanceEvent } from '~/types'

import { ItemTimeDisplay } from '../components/ItemTimeDisplay'
import { sessionRecordingPlayerLogic } from '../player/sessionRecordingPlayerLogic'
import { networkViewLogic } from './networkViewLogic'

function SimpleURL({ name, entryType }: { name: string | undefined; entryType: string | undefined }): JSX.Element {
    // TODO we should show hostname if it isn't the same as the navigation for the page(s) we're looking at

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

function NetworkStatus({ item }: { item: PerformanceEvent }): JSX.Element | null {
    return (
        <div className="flex flex-row gap-1 items-center whitespace-nowrap">
            <MethodTag item={item} label={false} />
            <StatusTag item={item} detailed={false} />
        </div>
    )
}

function Duration({ item }: { item: PerformanceEvent }): JSX.Element {
    const { formattedDurationFor } = useValues(networkViewLogic)
    return <div className="text-right">{formattedDurationFor(item)}</div>
}

function WaterfallMeta(): JSX.Element | null {
    const { currentPage, sizeBreakdown, page, pageCount } = useValues(networkViewLogic)
    const { prevPage, nextPage } = useActions(networkViewLogic)
    if (!currentPage[0]) {
        return null
    }

    const pageUrl = currentPage[0].name

    return (
        <>
            <div className="flex gap-x-2 px-2 justify-between">
                <LemonButton
                    onClick={prevPage}
                    icon={<IconChevronLeft />}
                    disabledReason={page === 0 ? "You're on the first page" : null}
                    type="secondary"
                    noPadding={true}
                    size="xsmall"
                />
                <div className="flex items-center gap-1 flex-1 justify-between overflow-hidden">
                    <ItemTimeDisplay
                        timestamp={dayjs(currentPage[0].timestamp)}
                        timeInRecording={currentPage[0].timeInRecording}
                        className="flex-shrink-0 p-0 min-w-4"
                    />

                    <Tooltip title={pageUrl}>
                        <Link to={pageUrl} target="_blank" className="block truncate">
                            {pageUrl}
                        </Link>
                    </Tooltip>
                </div>
                <LemonButton
                    onClick={nextPage}
                    icon={<IconChevronRight />}
                    disabledReason={page === pageCount - 1 ? "You're on the last page" : null}
                    type="secondary"
                    noPadding={true}
                    size="xsmall"
                />
            </div>
            <LemonDivider />
            <div className="px-4">
                <h3 className="mb-0">Page score</h3>
                <PerformanceCardRow item={currentPage[0]} />
                <AssetProportions data={sizeBreakdown} />
            </div>
        </>
    )
}

const MIN_TIMINGS_WIDTH = 80

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
            // Measure actual Status + Duration column widths from the rendered table header
            const ths = containerRef.current?.querySelectorAll('th')
            let otherColumnsWidth = 0
            if (ths && ths.length >= 4) {
                // Status (index 2) + Duration (index 3)
                otherColumnsWidth = ths[2].offsetWidth + ths[3].offsetWidth
            }
            const maxWidth = Math.max(200, containerWidth - otherColumnsWidth - MIN_TIMINGS_WIDTH)

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

export function NetworkView(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const logic = networkViewLogic({ sessionRecordingId: logicProps.sessionRecordingId })
    const { isLoading, currentPage, hasPageViews } = useValues(logic)
    const containerRef = useRef<HTMLDivElement>(null)
    const [urlColumnWidth, onUrlHeaderMouseDown] = useColumnResize(250, containerRef)

    if (isLoading) {
        return (
            <div className="flex flex-col px-4 py-2 deprecated-space-y-2">
                <LemonSkeleton repeat={10} fade={true} />
            </div>
        )
    }

    return (
        <BindLogic logic={networkViewLogic} props={{ sessionRecordingId: logicProps.sessionRecordingId }}>
            <div className="NetworkView overflow-y-auto py-2 px-4">
                <WaterfallMeta />
                <LemonDivider />
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div
                    ref={containerRef}
                    className="relative deprecated-space-y-1 px-0"
                    style={{ '--url-col-width': `${urlColumnWidth}px` } as React.CSSProperties}
                >
                    <div
                        className="NetworkView__column-resize absolute top-0 bottom-0 z-10 cursor-col-resize"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ left: urlColumnWidth }}
                        onMouseDown={onUrlHeaderMouseDown}
                    />
                    <LemonTable
                        className="NetworkView__table"
                        size="small"
                        dataSource={currentPage}
                        emptyState={
                            hasPageViews
                                ? 'error displaying network data'
                                : 'network data does not include any "navigation" events'
                        }
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
                                width: '100%',
                                render: function RenderTimings(_, item) {
                                    return <NetworkBar item={item} />
                                },
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                width: 0,
                                render: function RenderStatus(_, item) {
                                    return <NetworkStatus item={item} />
                                },
                            },
                            {
                                title: 'Duration',
                                key: 'duration',
                                width: 0,
                                align: 'right',
                                render: function RenderDuration(_, item) {
                                    return <Duration item={item} />
                                },
                            },
                        ]}
                    />
                </div>
            </div>
        </BindLogic>
    )
}
