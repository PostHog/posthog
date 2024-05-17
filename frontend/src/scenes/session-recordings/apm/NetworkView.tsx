import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { networkViewLogic } from './networkViewLogic'

export function NetworkView({ sessionRecordingId }: { sessionRecordingId: string }): JSX.Element {
    const { isLoading, sessionPlayerMetaData, allPerformanceEvents } = useValues(
        networkViewLogic({ sessionRecordingId })
    )

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
            <pre>{JSON.stringify(allPerformanceEvents, null, 2)}</pre>
        </>
    )
}
