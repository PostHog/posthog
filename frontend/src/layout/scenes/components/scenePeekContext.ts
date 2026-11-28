import { createContext, useContext } from 'react'

/**
 * True inside the item peek drawer. The drawer header already names the item and links to the full page,
 * so the scene title, the menu bar and the scene panel stay out of the peek.
 */
export const ScenePeekContext = createContext(false)

export function useIsScenePeek(): boolean {
    return useContext(ScenePeekContext)
}
