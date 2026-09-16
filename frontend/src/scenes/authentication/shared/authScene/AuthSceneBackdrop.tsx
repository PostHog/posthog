import './AuthScene.scss'

import { useValues } from 'kea'
import { type ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'

import { arrivedFromWebsiteLogic } from '../arrivedFromWebsiteLogic'

/**
 * Carries the light-mode button tokens in AuthScene.scss as well as the backdrop, which is what
 * turns LemonButton's primary amber on these screens. Owns no layout, so a scene that manages its
 * own height and scrolling can share it with the ones that use {@link AuthScene}.
 */
export function AuthSceneBackdrop({ className, children }: { className?: string; children: ReactNode }): JSX.Element {
    const { arrivedFromWebsite } = useValues(arrivedFromWebsiteLogic)

    return (
        <div
            className={cn(
                'AuthScene font-sans text-primary',
                arrivedFromWebsite && 'AuthScene--fromWebsite',
                className
            )}
        >
            {children}
        </div>
    )
}
