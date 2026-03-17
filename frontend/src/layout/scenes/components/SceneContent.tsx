import { useMountedLogic, useValues } from 'kea'
import { createContext } from 'react'

import { globalSetupLogic } from 'lib/components/ProductSetup'
import { cn } from 'lib/utils/css-classes'

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
    children: React.ReactNode
    className?: string
}

export function SceneContent({ children, className, ...rest }: SceneContentProps): JSX.Element {
    useMountedLogic(globalSetupLogic)
    const { sceneProductKey } = useValues(globalSetupLogic)

    return (
        <SceneContentContext.Provider value={{ productKey: sceneProductKey }}>
            <div className={cn('scene-content flex flex-col gap-y-4 relative z-10', className)} {...rest}>
                {children}
            </div>
        </SceneContentContext.Provider>
    )
}
