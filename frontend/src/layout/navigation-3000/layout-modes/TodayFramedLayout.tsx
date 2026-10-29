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

// Load the Today UI only behind the flag, so quill does not load on every page.
const TodayContextPanelFloating = lazyWithRetry(() =>
    import('~/layout/today/TodayContextPanelFloating').then((m) => ({ default: m.TodayContextPanelFloating }))
)
const TodayShell = lazyWithRetry(() => import('~/layout/today/TodayShell').then((m) => ({ default: m.TodayShell })))
const TodaySidePanel = lazyWithRetry(() =>
    import('~/layout/today/TodaySidePanel').then((m) => ({ default: m.TodaySidePanel }))
)
const TodayTopBar = lazyWithRetry(() => import('~/layout/today/TodayTopBar').then((m) => ({ default: m.TodayTopBar })))

export function TodayFramedLayout({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    const { mobileLayout } = useValues(navigationLogic)
    const { isLayoutNavCollapsed, navbarWidth, sidePanelWidth } = useValues(panelLayoutLogic)
    const { leftNavWidth, onAiPage, sidebarVisible } = useValues(todayShellLogic)

    const drawerOpen = mobileLayout && sidebarVisible

    return (
        <FullLayoutFrame
            className="TodayAppLayout scrollbar-thin scrollbar-track-transparent scrollbar-thumb-[var(--color-bg-fill-scroll-thumb)] TodayAppLayout--top-bar"
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
                <TodayTopBar />
            </Suspense>
            <Suspense fallback={null}>
                <TodayShell className="left-nav" />
            </Suspense>
            <div aria-hidden className="TodayAppLayout__shadow" />
            {/* The chrome token exists only in a quill scope, so the backdrop carries data-quill. */}
            <div data-quill aria-hidden className="TodayAppLayout__backdrop bg-[var(--chrome)]" />

            <MainContentColumn
                sceneConfig={sceneConfig}
                className={cn('TodayAppLayout__content', {
                    // A docked sidebar draws the corner and the seam.
                    'TodayAppLayout__content--corner': mobileLayout || !sidebarVisible,
                    'TodayAppLayout__content--side-panel': sidePanelWidth > 0,
                })}
                inert={drawerOpen}
                // The frame uses quill's border token to match the sidebar seam.
                frame={<div data-quill aria-hidden className="TodayAppLayout__frame" />}
                overlay={
                    !onAiPage && (
                        <Suspense fallback={null}>
                            <TodayContextPanelFloating />
                        </Suspense>
                    )
                }
            >
                {children}
            </MainContentColumn>

            <Suspense fallback={null}>
                <TodaySidePanel />
            </Suspense>
        </FullLayoutFrame>
    )
}
