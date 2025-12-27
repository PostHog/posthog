import { useValues } from 'kea'

import { colonDelimitedDuration } from 'lib/utils'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function PlayerFrameLLMMetaOverlay(): JSX.Element | null {
    const { currentURL, currentPlayerTime } = useValues(sessionRecordingPlayerLogic)

    if (!currentURL) {
        return null
    }

    return (
        <div className="bg-black text-white text-md px-2 pt-1 pb-2 flex justify-center gap-4 truncate">
            <span>
                <span className="font-bold">URL:</span> {currentURL}
            </span>
            <span>
                <span className="font-bold">Timestamp:</span> {colonDelimitedDuration(currentPlayerTime / 1000, null)}
            </span>
        </div>
    )
}
