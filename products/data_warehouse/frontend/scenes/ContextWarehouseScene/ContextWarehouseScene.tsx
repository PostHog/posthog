import type { ReactNode } from 'react'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ContextWarehouseRail, type ContextWarehouseSection } from './ContextWarehouseRail'

type ContextWarehouseSceneProps = {
    activeSection: ContextWarehouseSection
    findingCount: number
    onSectionChange: (section: ContextWarehouseSection) => void
    children: ReactNode
}

export function ContextWarehouseScene({
    activeSection,
    findingCount,
    onSectionChange,
    children,
}: ContextWarehouseSceneProps): JSX.Element {
    return (
        <SceneContent className="@container/context-warehouse pt-4">
            <SceneTitleSection
                name="Context warehouse"
                description="Build, understand, and operate the data your team uses in PostHog."
                resourceType={{ type: 'data_warehouse' }}
            />
            <div className="flex min-w-0 flex-col items-start gap-5 @min-[64rem]/context-warehouse:flex-row @min-[64rem]/context-warehouse:gap-6">
                <ContextWarehouseRail
                    activeSection={activeSection}
                    findingCount={findingCount}
                    onSectionChange={onSectionChange}
                />
                <main className="min-w-0 w-full flex-1">{children}</main>
            </div>
        </SceneContent>
    )
}
