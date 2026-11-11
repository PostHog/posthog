import { PreviewCard } from '@base-ui/react/preview-card'
import { createContext, useCallback, useContext, useEffect, useRef } from 'react'

import { TodayPreviewPayload } from './todayPreviewCards'

export interface TodayPreviewCard {
    handle: PreviewCard.Handle<TodayPreviewPayload>
    /** A row's menu reports here, so the card closes while the menu is open and stays shut until it closes. */
    setMenuOpen: (open: boolean) => void
}

export const TodayPreviewCardContext = createContext<TodayPreviewCard | null>(null)

/** For a row menu's `onOpenChange`. Outside the sidebar there is no card, so the report goes nowhere. */
export function useTodayPreviewMenuReport(): (open: boolean) => void {
    const setMenuOpen = useContext(TodayPreviewCardContext)?.setMenuOpen
    const reportedOpen = useRef(false)
    // A menu that unmounts while open reports no close, which would keep the card shut for good.
    useEffect(
        () => () => {
            if (reportedOpen.current) {
                setMenuOpen?.(false)
            }
        },
        [setMenuOpen]
    )
    return useCallback(
        (open: boolean) => {
            reportedOpen.current = open
            setMenuOpen?.(open)
        },
        [setMenuOpen]
    )
}
