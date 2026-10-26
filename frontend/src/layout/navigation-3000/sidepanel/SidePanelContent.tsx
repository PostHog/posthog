import { useActions } from 'kea'
import { ComponentType, memo, Suspense } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'
import { ChunkLoadErrorBoundary } from 'scenes/ChunkLoadErrorBoundary'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { SidePanelTab } from '~/types'

import { SidePanelNavigation } from './SidePanelNavigation'
import { sidePanelStateLogic } from './sidePanelStateLogic'

export const SidePanelContent = memo(function SidePanelContent({
    activeTab,
    Content,
}: {
    activeTab: SidePanelTab
    Content: ComponentType
}): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <SidePanelNavigation activeTab={activeTab} onTabChange={openSidePanel}>
            <ErrorBoundary>
                <ChunkLoadErrorBoundary>
                    <Suspense fallback={<Spinner className="text-4xl mx-auto mt-16" />}>
                        <Content />
                    </Suspense>
                </ChunkLoadErrorBoundary>
            </ErrorBoundary>
        </SidePanelNavigation>
    )
})
