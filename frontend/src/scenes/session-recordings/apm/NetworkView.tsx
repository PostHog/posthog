import { useActions, useValues } from 'kea'
import { IconChevronLeft, IconChevronRight } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { networkViewLogic } from './networkViewLogic'

export function NetworkView({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    const logic = networkViewLogic({ sessionRecordingId })
    const { page, pageCount, isLoading, sessionPlayerMetaData, currentPage } = useValues(logic)
    const { prevPage, nextPage } = useActions(logic)

    if (isLoading) {
        return (
            <div className="flex flex-col px-4 py-2 space-y-2">
                <LemonSkeleton repeat={10} fade={true} />
            </div>
        )
    }
    return (
        <>
            draw the rest of the owl
            <div className="pre">{sessionRecordingId}</div>
            <div className="pre">{JSON.stringify(sessionPlayerMetaData, null, 2)}</div>
            <div className="w-full flex flex-row">
                <LemonButton
                    onClick={() => prevPage()}
                    className="mr-2"
                    icon={<IconChevronLeft />}
                    disabledReason={page === 0 ? "You're on the first page" : null}
                    type="secondary"
                    noPadding={true}
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
                />
            </div>
            <pre>{JSON.stringify(currentPage, null, 2)}</pre>
        </>
    )
}
