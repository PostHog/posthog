import { useValues } from 'kea'

import { colonDelimitedDuration } from 'lib/utils'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerFrameLLMMetaOverlay(): JSX.Element | null {
    const { currentURL, currentPlayerTime, currentSegment } = useValues(sessionRecordingPlayerLogic)

    if (!currentURL || currentPlayerTime === undefined) {
        return null
    }

    const isInactive = currentSegment?.isActive === false

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 flex justify-center gap-4 truncate font-mono">
            <span>
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">TIMESTAMP:</span> {colonDelimitedDuration(currentPlayerTime / 1000, null)}
            </span>
            {isInactive && (
                <span>
                    <span className="font-bold text-yellow-400">[IDLE]</span>
                </span>
            )}
        </div>
    )
}
