import { LemonCollapse, LemonTag } from '@posthog/lemon-ui'
import { useActions, useMountedLogic, useValues } from 'kea'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AiFilterInput } from './AiFilterInput'
import { aiFilterLogic } from './aiFilterLogic'
import { AiFilterSuggestions } from './AiFilterSuggestions'
import { AiFilterThread } from './AiFilterThread'

export function AiFilter(): JSX.Element {
    const mountedLogic = useMountedLogic(sessionRecordingsPlaylistLogic)
    const { setFilters, resetFilters } = useActions(mountedLogic)
    const filterLogic = aiFilterLogic({ setFilters, resetFilters })
    const { messages } = useValues(filterLogic)

    return (
        <>
            <LemonCollapse
                className="mb-2"
                panels={[
                    {
                        key: 'chat-with-recordings',
                        header: (
                            <div className="no-flex py-2">
                                <h3 className="mb-0 flex items-center gap-1">
                                    Chat with your recording list <LemonTag type="completion">ALPHA</LemonTag>
                                </h3>
                                <div className="text-xs font-normal text-muted-alt">
                                    Ask Max AI to find recordings matching your needs - like "show me recordings with
                                    rage clicks" or "find recordings where users visited pricing"
                                </div>
                            </div>
                        ),
                        content: (
                            <>
                                <div className="relative flex flex-col gap-3 px-4 items-center grow justify-center">
                                    <AiFilterThread />
                                    <AiFilterInput />
                                    {messages.length === 0 && <AiFilterSuggestions />}
                                </div>
                            </>
                        ),
                    },
                ]}
            />
        </>
    )
}
