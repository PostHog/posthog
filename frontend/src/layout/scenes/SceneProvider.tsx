import { useMemo } from 'react'

import { SceneLayoutContext, SceneLayoutContextValue } from './SceneLayoutContext'

export interface SceneProviderProps {
    className?: string
    children: React.ReactNode
}

export function SceneProvider({ className, children }: SceneProviderProps): JSX.Element {
    const contextValue: SceneLayoutContextValue = useMemo(() => ({ className }), [className])

    return <SceneLayoutContext.Provider value={contextValue}>{children}</SceneLayoutContext.Provider>
}
