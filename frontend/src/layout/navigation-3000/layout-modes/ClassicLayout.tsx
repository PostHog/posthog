import { useValues } from 'kea'
import { CSSProperties, ReactNode } from 'react'

import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

import { navigationLogic } from '../../navigation/navigationLogic'
import { PanelLayout } from '../../panel-layout/PanelLayout'
import { panelLayoutLogic } from '../../panel-layout/panelLayoutLogic'
import { FullLayoutFrame } from '../components/FullLayoutFrame'
import { MainContentColumn } from '../components/MainContentColumn'
import { SidePanel } from '../sidepanel/SidePanel'
import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'

export function ClassicLayout({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    const { mobileLayout } = useValues(navigationLogic)
    const { isLayoutNavCollapsed, navbarWidth, sidePanelWidth } = useValues(panelLayoutLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    return (
        <FullLayoutFrame
            className={cn({ 'app-layout--mobile': mobileLayout })}
            style={
                {
                    '--scene-layout-background': sceneConfig?.canvasBackground
                        ? 'var(--color-bg-surface-primary)'
                        : 'var(--color-bg-primary)',
                    '--side-panel-width': sidePanelWidth + 'px',
                    '--project-navbar-width': !mobileLayout && !isLayoutNavCollapsed ? `${navbarWidth}px` : undefined,
                    '--left-nav-width': isLayoutNavCollapsed
                        ? 'var(--project-navbar-width-collapsed)'
                        : 'var(--project-navbar-width)',
                } as CSSProperties
            }
        >
            <PanelLayout className="left-nav" />
            <MainContentColumn
                sceneConfig={sceneConfig}
                className={cn('lg:rounded border-t lg:border lg:mr-1 lg:mb-1 lg:mt-1', {
                    'rounded-r-none': sidePanelOpen,
                })}
                sidePanel={<SidePanel />}
                sidePanelOverlapsMain={sidePanelOpen}
            >
                {children}
            </MainContentColumn>
        </FullLayoutFrame>
    )
}
