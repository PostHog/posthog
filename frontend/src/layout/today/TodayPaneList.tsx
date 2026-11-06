import './TodayShell.scss'

import { type ReactNode, createContext, useContext } from 'react'

import { Autocomplete, AutocompleteList } from '@posthog/quill'

const TodayPaneListContext = createContext(false)

/** Rows in a list without a search field take Tab focus, since no input is there to move the highlight. */
export function useInTodayPaneList(): boolean {
    return useContext(TodayPaneListContext)
}

/** The list of a sidebar pane that has no search field. Its rows are list options, so they need the list around them. */
export function TodayPaneList({ children }: { children: ReactNode }): JSX.Element {
    return (
        <Autocomplete<string> inline open value="" filter={null}>
            <div className="flex min-h-0 flex-1 flex-col">
                <AutocompleteList className="TodayPaneSearchList mt-2 min-h-0 !max-h-none flex-1 overflow-y-auto !p-0 pb-6">
                    <TodayPaneListContext.Provider value={true}>{children}</TodayPaneListContext.Provider>
                </AutocompleteList>
            </div>
        </Autocomplete>
    )
}
