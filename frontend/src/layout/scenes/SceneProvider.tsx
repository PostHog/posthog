import { useActions } from 'kea'
import { useEffect } from 'react'

import { sceneLayoutLogic } from './sceneLayoutLogic'

export interface SceneProviderProps {
    className?: string
    children: React.ReactNode
}

export function SceneProvider({ className, children }: SceneProviderProps): JSX.Element {
    const { setSceneContextClassName } = useActions(sceneLayoutLogic)

    useEffect(() => {
        setSceneContextClassName(className)
        return () => {
            setSceneContextClassName(undefined)
        }
    }, [className, setSceneContextClassName])

    return <>{children}</>
}
