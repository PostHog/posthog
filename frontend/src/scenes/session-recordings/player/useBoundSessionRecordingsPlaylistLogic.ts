import { BuiltLogic, getContext } from 'kea'
import { Context, createContext, useContext } from 'react'

import {
    sessionRecordingsPlaylistLogic,
    sessionRecordingsPlaylistLogicType,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

// Stands in for pages with no <BindLogic logic={sessionRecordingsPlaylistLogic}> ancestor (e.g. the
// standalone /replay/:id player). Reading the logic bare there would auto-mount a phantom `--`-keyed
// instance shared by every other bare reader on the page — harmless alone, but torn down out from
// under the others the moment any one of them unmounts, throwing "[KEA] Can not find path" on the
// next store update any of them reads. `mount` is a no-op, so nothing joins that shared instance.
const UNBOUND_PLAYLIST_LOGIC = {
    pathString: 'unbound-session-recordings-playlist-logic',
    selectors: {},
    actions: {},
    mount: () => () => {},
} as unknown as BuiltLogic<sessionRecordingsPlaylistLogicType>

const fallbackReactContext = createContext<BuiltLogic<sessionRecordingsPlaylistLogicType> | undefined>(undefined)

/**
 * Resolves the sessionRecordingsPlaylistLogic instance bound by an ancestor <BindLogic>, without
 * ever building or mounting the logic itself. Pass the result to `useValues`/`useActions` instead
 * of reading `sessionRecordingsPlaylistLogic` bare in components that also render where no playlist
 * is bound.
 */
export function useBoundSessionRecordingsPlaylistLogic(): BuiltLogic<sessionRecordingsPlaylistLogicType> {
    const boundLogicContext = getContext().react.contexts.get(sessionRecordingsPlaylistLogic) as
        | Context<BuiltLogic<sessionRecordingsPlaylistLogicType> | undefined>
        | undefined
    const boundLogic = useContext(boundLogicContext ?? fallbackReactContext)
    return boundLogic ?? UNBOUND_PLAYLIST_LOGIC
}
