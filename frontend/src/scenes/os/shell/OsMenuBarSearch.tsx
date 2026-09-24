import { useActions } from 'kea'

import { IconSearch } from '@posthog/icons'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { osSpotlightLogic } from '../spotlight/osSpotlightLogic'

/** The search field in the middle of the menu bar. It only opens the spotlight, which does the searching. */
export function OsMenuBarSearch(): JSX.Element {
    const { openSpotlight } = useActions(osSpotlightLogic)

    return (
        <button
            type="button"
            className="OsShell__search"
            onClick={() => openSpotlight()}
            aria-haspopup="dialog"
            aria-keyshortcuts="Meta+K Control+K"
            data-attr="os-menu-search"
        >
            <IconSearch className="size-4 shrink-0" />
            <span className="flex-1 min-w-0 truncate text-left">Search or open an app</span>
            <KeyboardShortcut command k className="shrink-0" />
        </button>
    )
}
