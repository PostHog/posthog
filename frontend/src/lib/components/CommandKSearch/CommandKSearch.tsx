import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { CommandKSearchPalette } from './CommandKSearchPalette'

/** Command K search with smart filters. The UX contract lives in COMMAND_K_SEARCH_UX.md next to this file. */
export function CommandKSearch(): JSX.Element | null {
    const { todayRailEnabled } = useValues(todayShellLogic)
    // kea mounts a logic while React renders, and unmounts it only when that render commits and later unmounts.
    // When this chunk loads, React renders the palette in a pass it can interrupt, and a store update in that
    // pass makes React restart it without an unmount. The logic then stays mounted after the palette closes,
    // so the next open shows the previous query. A state update from an effect renders in a pass that React
    // does not interrupt, so the logic mounts once for each open of the palette.
    const [hasCommitted, setHasCommitted] = useState(false)
    useEffect(() => setHasCommitted(true), [])
    return hasCommitted || !todayRailEnabled ? <CommandKSearchPalette /> : null
}
