import { useMountedLogic, useValues } from 'kea'
import { createContext } from 'react'

import { globalSetupLogic } from 'lib/components/ProductSetup'
import { cn } from 'lib/utils/css-classes'

import { sceneWidthLogic } from '~/layout/scenes/sceneWidthLogic'
import type { ProductKey } from '~/queries/schema/schema-general'

/**
 * Context to provide the sceneProductKey to child components (like SceneTitleSection)
 * for reference. The value is synced from sceneLogic via globalSetupLogic.
 */
interface SceneContentContextValue {
    productKey: ProductKey | null
}

export const SceneContentContext = createContext<SceneContentContextValue>({ productKey: null })

interface SceneContentProps extends React.HTMLAttributes<HTMLDivElement> {
    /** Uses the whole width even when the viewer turned off full width for this scene, as fullscreen modes need. */
    fullWidth?: boolean
}

export function SceneContent({ children, className, fullWidth, ...rest }: SceneContentProps): JSX.Element {
    useMountedLogic(globalSetupLogic)
    const { sceneProductKey } = useValues(globalSetupLogic)
    const { isSceneFullWidth } = useValues(sceneWidthLogic)

    return (
        <SceneContentContext.Provider value={{ productKey: sceneProductKey }}>
            <div
                className={cn(
                    'scene-content flex flex-col gap-y-4 relative z-10',
                    !fullWidth && !isSceneFullWidth && 'scene-content--narrow',
                    className
                )}
                {...rest}
            >
                {children}
            </div>
        </SceneContentContext.Provider>
    )
}
