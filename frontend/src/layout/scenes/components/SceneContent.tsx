import { useActions, useMountedLogic } from 'kea'
import { createContext, useEffect } from 'react'

import { PRODUCTS_WITH_SETUP, globalSetupLogic } from 'lib/components/ProductSetup'
import { cn } from 'lib/utils/css-classes'

import type { ProductKey } from '~/queries/schema/schema-general'

export interface SceneContentProps {
    children: React.ReactNode
    className?: string
    /**
     * When provided, locks the Quick Start popover to this product.
     * The user won't be able to switch products while on this scene.
     * The Quick Start button appears globally for new organizations.
     */
    productKey?: ProductKey
}

/**
 * Context to provide the productKey to child components (like SceneTitleSection)
 * for reference. Auto-selection is handled via globalSetupLogic.
 */
export const SceneContentContext = createContext<{
    productKey?: ProductKey
}>({})

export function SceneContent({ children, className, productKey }: SceneContentProps): JSX.Element {
    useMountedLogic(globalSetupLogic)
    const { setSceneProductKey } = useActions(globalSetupLogic)

    // Set/clear the scene product key when entering/leaving the scene
    useEffect(() => {
        if (productKey && PRODUCTS_WITH_SETUP.includes(productKey)) {
            setSceneProductKey(productKey)
        } else {
            setSceneProductKey(null)
        }

        // Clear when unmounting
        return () => {
            setSceneProductKey(null)
        }
    }, [productKey, setSceneProductKey])

    return (
        <SceneContentContext.Provider value={{ productKey }}>
            <div className={cn('scene-content flex flex-col gap-y-4 relative', className)}>{children}</div>
        </SceneContentContext.Provider>
    )
}
