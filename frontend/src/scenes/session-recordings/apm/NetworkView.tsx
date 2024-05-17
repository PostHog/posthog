import { useActions, useValues } from 'kea'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

import { networkViewLogic } from './networkViewLogic'

export function NetworkView({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    const logic = networkViewLogic({ sessionRecordingId })
    const { page, pageCount, isLoading, currentPage, sessionPerson } = useValues(logic)
    const { prevPage, nextPage } = useActions(logic)

    if (isLoading) {
        return (
            <div className="flex flex-col px-4 py-2 space-y-2">
                <LemonSkeleton repeat={10} fade={true} />
            </div>
        )
    }
    return (
        <div className="px-4 py-2">
            {/*<div className="pre">{JSON.stringify(sessionPlayerMetaData, null, 2)}</div>*/}
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
            <pre>{JSON.stringify(currentPage, null, 2)}</pre>
        </div>
    )
}
