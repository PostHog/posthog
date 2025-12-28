import { useValues } from 'kea'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerFrameMetaOverlay(): JSX.Element | null {
    const { currentURL, currentPlayerTime, currentSegment } = useValues(sessionRecordingPlayerLogic)

    if (!currentURL || currentPlayerTime === undefined) {
        return null
    }

    const isInactive = currentSegment?.isActive === false

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 flex justify-center gap-4 font-mono truncate">
            <span className="truncate">
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">REC_T:</span> {Math.floor(currentPlayerTime / 1000)}
            </span>
            {isInactive && (
                <span>
                    <span className="font-bold text-yellow-400">[IDLE]</span>
                </span>
            )}
        </div>
    )
}
