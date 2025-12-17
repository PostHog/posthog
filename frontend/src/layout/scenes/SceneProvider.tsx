import { useActions } from 'kea'
import { useEffect } from 'react'

import { sceneLayoutLogic } from './sceneLayoutLogic'

export interface SceneProviderProps {
    className?: string
    children: React.ReactNode
    tabId?: string
}

export function SceneProvider({ className, children, tabId }: SceneProviderProps): JSX.Element {
    const { setSceneContextClassName } = useActions(sceneLayoutLogic)

    useEffect(() => {
        setSceneContextClassName(tabId, className)
        return () => {
            setSceneContextClassName(tabId, undefined)
        }
    }, [className, tabId, setSceneContextClassName])

    return <>{children}</>
}
