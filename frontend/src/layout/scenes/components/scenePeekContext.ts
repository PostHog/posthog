import { createContext, useContext } from 'react'

// The peek drawer header names the item and links to it, so scene chrome inside a peek renders nothing.
export const ScenePeekContext = createContext(false)

export function useIsScenePeek(): boolean {
    return useContext(ScenePeekContext)
}
