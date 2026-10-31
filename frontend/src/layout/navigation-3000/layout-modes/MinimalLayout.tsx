import { ReactNode } from 'react'

import { SceneConfig } from 'scenes/sceneTypes'

import { MinimalNavigation } from '../components/MinimalNavigation'
import { SimpleLayoutFrame } from '../components/SimpleLayoutFrame'

export function MinimalLayout({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    return (
        <SimpleLayoutFrame
            nav={<MinimalNavigation />}
            mainClassName={sceneConfig?.layout !== 'plain' ? '@container/main-content flex flex-col p-4' : undefined}
        >
            {children}
        </SimpleLayoutFrame>
    )
}
