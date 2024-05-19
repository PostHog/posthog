import { BindLogic, useActions, useValues } from 'kea'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
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
                <span>
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
        <div className="flex flex-row justify-between">
            <MethodTag item={item} label={false} />
            <StatusTag item={item} label={false} />
        </div>
    )
}

function Duration({ item }: { item: PerformanceEvent }): JSX.Element {
    const { formattedDurationFor } = useValues(networkViewLogic)
    return <div className="text-right">{formattedDurationFor(item)}</div>
}

function WaterfallRow({ item }: { item: PerformanceEvent }): JSX.Element | null {
    return (
        <div className="flex flex-row">
            <div className="w-2/5 overflow-x-hidden ellipsis">
                <SimpleURL name={item.name} entryType={item.entry_type} />
            </div>
            <div className="flex-1 grow relative">
                <NetworkBar item={item} />
            </div>
            <div className="w-1/12">
                <NetworkStatus item={item} />
            </div>
            <div className="w-1/12">
                <Duration item={item} />
            </div>
        </div>
    )
}

function WaterfallMeta(): JSX.Element {
    const { page, pageCount, currentPage, sessionPerson } = useValues(networkViewLogic)
    const { prevPage, nextPage } = useActions(networkViewLogic)

    return (
        <>
            <div>
                <div className="flex flex-row flex-wrap items-center justify-between">
                    <h2 className="m-0">{currentPage[0].name}</h2>
                    <div>
                        <PersonDisplay person={sessionPerson} withIcon={true} noEllipsis={true} />
                    </div>
                </div>
            </div>
            <LemonDivider />
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
            <LemonDivider />
            <PerformanceCardRow item={currentPage[0]} />
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
            <div className="px-4 py-2">
                {/*<div className="pre">{JSON.stringify(sessionPlayerMetaData, null, 2)}</div>*/}
                <WaterfallMeta />
                <LemonDivider />
                <div className="space-y-1">
                    {currentPage.map((cp, i) => (
                        <WaterfallRow key={`${i}-${cp.name}`} item={cp} />
                    ))}
                </div>
            </div>
        </BindLogic>
    )
}
