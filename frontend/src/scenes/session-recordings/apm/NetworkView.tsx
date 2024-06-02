import './NetworkView.scss'

import { LemonTable, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import AssetProportions from 'scenes/session-recordings/apm/components/AssetProportions'
import { PerformanceCardRow } from 'scenes/session-recordings/apm/components/PerformanceCard'
import { MethodTag, StatusTag } from 'scenes/session-recordings/apm/playerInspector/ItemPerformanceEvent'
import { NetworkBar } from 'scenes/session-recordings/apm/waterfall/NetworkBar'

import { PerformanceEvent } from '~/types'

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
                    <div className="flex flex-col space-y-2">
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
                    {url.hash.length || url.search.length ? '...' : null}
                </span>
            </Tooltip>
        )
    } catch {
        return <span>{name}</span>
    }
}

function NetworkStatus({ item }: { item: PerformanceEvent }): JSX.Element | null {
    return (
        <div className="flex flex-row justify-around">
            <MethodTag item={item} label={false} />
            <StatusTag item={item} detailed={false} />
        </div>
    )
}

function Duration({ item }: { item: PerformanceEvent }): JSX.Element {
    const { formattedDurationFor } = useValues(networkViewLogic)
    return <div className="text-right">{formattedDurationFor(item)}</div>
}

function Pager(): JSX.Element {
    const { page, pageCount } = useValues(networkViewLogic)
    const { prevPage, nextPage } = useActions(networkViewLogic)

    return (
        <div className="flex space-x-2">
            <LemonButton
                onClick={prevPage}
                icon={<IconChevronLeft />}
                disabledReason={page === 0 ? "You're on the first page" : null}
                type="secondary"
                noPadding={true}
                size="xsmall"
            />
            <div className="text-center whitespace-nowrap font-medium">
                {page + 1} of {pageCount}
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
    )
}

function WaterfallMeta(): JSX.Element | null {
    const { currentPage, sizeBreakdown } = useValues(networkViewLogic)

    if (!currentPage[0]) {
        return null
    }

    const pageUrl = currentPage[0].name

    return (
        <>
            <div className="flex space-x-12 px-4 justify-between">
                <span className="flex items-center gap-1 truncate">
                    <Link to={pageUrl} target="_blank" className="truncate">
                        {pageUrl}
                    </Link>
                    {pageUrl && (
                        <span className="flex items-center">
                            <CopyToClipboardInline
                                description={pageUrl}
                                explicitValue={pageUrl}
                                iconStyle={{ color: 'var(--muted-alt)' }}
                                selectable={true}
                            />
                        </span>
                    )}
                </span>

                <Pager />
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

export function NetworkView({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    const logic = networkViewLogic({ sessionRecordingId })
    const { isLoading, currentPage, hasPageViews } = useValues(logic)

    if (isLoading) {
        return (
            <div className="flex flex-col px-4 py-2 space-y-2">
                <LemonSkeleton repeat={10} fade={true} />
            </div>
        )
    }

    return (
        <BindLogic logic={networkViewLogic} props={{ sessionRecordingId }}>
            <div className="NetworkView overflow-auto py-2">
                <WaterfallMeta />
                <LemonDivider />
                <div className="space-y-1 px-4">
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
                                width: 250,
                                render: function RenderUrl(_, item) {
                                    return <SimpleURL name={item.name} entryType={item.entry_type} />
                                },
                            },
                            {
                                title: 'Timings',
                                key: 'timings',
                                render: function RenderUrl(_, item) {
                                    return <NetworkBar item={item} />
                                },
                            },
                            {
                                title: 'Status',
                                key: 'status',
                                width: 128,
                                render: function RenderUrl(_, item) {
                                    return <NetworkStatus item={item} />
                                },
                            },
                            {
                                title: 'Duration',
                                key: 'duration',
                                width: 86,
                                render: function RenderUrl(_, item) {
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
