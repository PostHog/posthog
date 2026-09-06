import type { ReactNode } from 'react'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

type ContextWarehouseSceneProps = {
    children: ReactNode
}

export function ContextWarehouseScene({ children }: ContextWarehouseSceneProps): JSX.Element {
    return (
        <SceneContent className="@container/context-warehouse pt-2">
            <SceneTitleSection
                name="Context warehouse"
                description="Build, understand, and operate the data your team uses in PostHog."
                resourceType={{ type: 'data_warehouse' }}
            />
            <div className="min-w-0 w-full">{children}</div>
        </SceneContent>
    )
}
