import { useValues } from 'kea'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { currentURL, currentPlayerTime, currentSegment, endReached } = useValues(sessionRecordingPlayerLogic)

    if (!currentURL || currentPlayerTime === undefined) {
        return null
    }

    const isInactive = currentSegment?.isActive === false

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 h-8 flex items-center justify-center gap-4 font-mono truncate">
            <span className="truncate">
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">REC_T:</span> {Math.floor(currentPlayerTime / 1000)}
            </span>
            {endReached ? (
                <span className="font-bold text-green-400">[REACHED THE END OF THE RECORDING]</span>
            ) : isInactive ? (
                <span className="font-bold text-yellow-400">[IDLE - SKIPPING INACTIVITY]</span>
            ) : null}
        </div>
    )
}
