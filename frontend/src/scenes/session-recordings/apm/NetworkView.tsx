import './NetworkView.scss'

import { LemonTable } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
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
            <StatusTag item={item} label={false} />
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
        <div className="w-full flex flex-row">
            <LemonButton
                onClick={() => prevPage()}
                className="mr-2"
                icon={<IconChevronLeft />}
                disabledReason={page === 0 ? "You're on the first page" : null}
                type="secondary"
                noPadding={true}
                size="xsmall"
            />
            <div className="flex-grow text-center">
                viewing page {page + 1} of {pageCount} in this session
            </div>
            <LemonButton
                onClick={() => nextPage()}
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

    return (
        <>
            <div>
                <div className="flex flex-row flex-nowrap items-center justify-between space-x-2">
                    {/*we shouldn't need to check for currentPage[0] with the elvis operator here,
                    but React is so eager to just call functions willy-nilly*/}
                    <h2 className="m-0 truncate">{currentPage[0].name}</h2>
                </div>
            </div>
            <LemonDivider />
            <Pager />
            <LemonDivider />
            <h3 className="mb-0">Page score</h3>
            <PerformanceCardRow item={currentPage[0]} />
            <AssetProportions data={sizeBreakdown} />
        </>
    )
}

export function NetworkView({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    const logic = networkViewLogic({ sessionRecordingId })
    const { isLoading, currentPage } = useValues(logic)

    if (isLoading) {
        return (
            <div className="flex flex-col px-4 py-2 space-y-2">
                <LemonSkeleton repeat={10} fade={true} />
            </div>
        )
    }

    return (
        <BindLogic logic={networkViewLogic} props={{ sessionRecordingId }}>
            <div className="NetworkView overflow-auto px-4 py-2">
                <WaterfallMeta />
                <LemonDivider />
                <div className="space-y-1">
                    <LemonTable
                        className="NetworkView__table"
                        size="small"
                        dataSource={currentPage}
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
