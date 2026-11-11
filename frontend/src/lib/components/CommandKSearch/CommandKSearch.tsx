import { useEffect, useState } from 'react'

import { CommandKSearchPalette } from './CommandKSearchPalette'

/** Command K search with smart filters. The UX contract lives in COMMAND_K_SEARCH_UX.md next to this file. */
export function CommandKSearch(): JSX.Element | null {
    // kea mounts a logic during render, and React can restart the render that loads this chunk without an unmount,
    // which leaks the logic and its query. Rendering after the first commit mounts the logic once for each open.
    const [hasCommitted, setHasCommitted] = useState(false)
    useEffect(() => setHasCommitted(true), [])
    return hasCommitted ? <CommandKSearchPalette /> : null
}
