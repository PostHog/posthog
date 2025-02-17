import { useActions, useMountedLogic, useValues } from 'kea'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AiFilterInput } from './AiFilterInput'
import { AiFilterIntro } from './AiFilterIntro'
import { aiFilterLogic } from './aiFilterLogic'
import { AiFilterSuggestions } from './AiFilterSuggestions'
import { AiFilterThread } from './AiFilterThread'

export function AiFilter({ isExpanded }: { isExpanded: boolean }): JSX.Element {
    const mountedLogic = useMountedLogic(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters } = useActions(mountedLogic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages } = useValues(filterLogic)

    return (
        <div className="relative flex flex-col gap-3 px-4 items-center grow justify-center">
            {messages.length === 0 && <AiFilterIntro />}
            <AiFilterThread />
            {isExpanded && <AiFilterInput />}
            {messages.length === 0 && <AiFilterSuggestions />}
        </div>
    )
}
