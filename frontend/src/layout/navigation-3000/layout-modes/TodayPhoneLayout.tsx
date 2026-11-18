import { useValues } from 'kea'
import { CSSProperties, ReactNode, Suspense } from 'react'

import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { SceneConfig } from 'scenes/sceneTypes'

import { navigationLogic } from '../../navigation/navigationLogic'
import { panelLayoutLogic } from '../../panel-layout/panelLayoutLogic'
import { TODAY_RAIL_WIDTH, todayShellLogic } from '../../today/todayShellLogic'
import { FullLayoutFrame } from '../components/FullLayoutFrame'
import { MainContentColumn } from '../components/MainContentColumn'
import { SidePanel } from '../sidepanel/SidePanel'
import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'

const TodayShell = lazyWithRetry(() => import('~/layout/today/TodayShell').then((m) => ({ default: m.TodayShell })))

export function TodayPhoneLayout({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    const { mobileLayout } = useValues(navigationLogic)
    const { isLayoutNavCollapsed, navbarWidth, sidePanelWidth } = useValues(panelLayoutLogic)
    const { leftNavWidth, phoneHeaderHidden, sidebarVisible } = useValues(todayShellLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)

    const drawerOpen = mobileLayout && sidebarVisible

    return (
        <FullLayoutFrame
            className={cn(
                'app-layout--mobile TodayAppLayout scrollbar-thin scrollbar-track-transparent scrollbar-thumb-[var(--color-bg-fill-scroll-thumb)] TodayAppLayout--phone',
                { 'TodayAppLayout--no-phone-header': phoneHeaderHidden }
            )}
            style={
                {
                    '--scene-layout-background': 'var(--color-bg-primary)',
                    '--side-panel-width': sidePanelWidth + 'px',
                    '--project-navbar-width': !mobileLayout && !isLayoutNavCollapsed ? `${navbarWidth}px` : undefined,
                    '--today-rail-width': `${TODAY_RAIL_WIDTH}px`,
                    '--left-nav-width': `${leftNavWidth}px`,
                } as CSSProperties
            }
        >
            <Suspense fallback={null}>
                <TodayShell className="left-nav" />
            </Suspense>

            <MainContentColumn
                sceneConfig={sceneConfig}
                inert={drawerOpen}
                sidePanel={<SidePanel />}
                sidePanelOverlapsMain={sidePanelOpen}
            >
                {children}
            </MainContentColumn>
        </FullLayoutFrame>
    )
}
