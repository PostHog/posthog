import { createContext, useContext } from 'react'

export interface TodaySheetMenuControls {
    close: () => void
    back: () => void
    openPage: (pageId: string, title: string) => void
    activePageId: string | null
    pageContainer: HTMLElement | null
}

export const TodaySheetMenuContext = createContext<TodaySheetMenuControls | null>(null)

export function useTodaySheetMenu(): TodaySheetMenuControls | null {
    return useContext(TodaySheetMenuContext)
}
