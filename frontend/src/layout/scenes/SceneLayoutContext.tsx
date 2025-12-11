import { createContext, useContext } from 'react'

export interface SceneLayoutContextValue {
    className?: string
}

export const SceneLayoutContext = createContext<SceneLayoutContextValue>({})

export function useSceneLayoutContext(): SceneLayoutContextValue {
    return useContext(SceneLayoutContext)
}
