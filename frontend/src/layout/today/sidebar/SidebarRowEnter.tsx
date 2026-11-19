import './sidebar.scss'

import { useActions, useValues } from 'kea'

import { sidebarPinsLogic } from './sidebarPinsLogic'

/** Wraps a pinned row. The pin a person just made slides in once, so they see where it went. */
export function SidebarRowEnter({ pinKey, children }: { pinKey: string; children: JSX.Element }): JSX.Element {
    const { recentlyPinnedKey } = useValues(sidebarPinsLogic)
    const { clearRecentlyPinned } = useActions(sidebarPinsLogic)
    if (pinKey !== recentlyPinnedKey) {
        return children
    }
    return (
        <div
            className="SidebarRowEnter"
            onAnimationEnd={(event) => {
                // The row's own slide bubbles up here as well. The room it opens ends the motion.
                if (event.target === event.currentTarget) {
                    clearRecentlyPinned()
                }
            }}
        >
            <div className="SidebarRowEnter__row">{children}</div>
        </div>
    )
}
