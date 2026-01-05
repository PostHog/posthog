import './Navigation.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'

import { ProjectNotice } from '../navigation/ProjectNotice'
import { navigationLogic } from '../navigation/navigationLogic'
import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import { SceneLayout } from '../scenes/SceneLayout'
import { MinimalNavigation } from './components/MinimalNavigation'
import { navigation3000Logic } from './navigationLogic'
import { SidePanel } from './sidepanel/SidePanel'
import { themeLogic } from './themeLogic'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    const { theme } = useValues(themeLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { mode } = useValues(navigation3000Logic)
    const mainRef = useRef<HTMLElement>(null)
    const { mainContentRect } = useValues(panelLayoutLogic)
    const { setMainContentRef, setMainContentRect } = useActions(panelLayoutLogic)
    const { setTabScrollDepth } = useActions(sceneLogic)
    const { activeTabId } = useValues(sceneLogic)

    // Set container ref so we can measure the width of the scene layout in logic
    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
            // Set main content rect so we can measure the width of the scene layout in logic
            setMainContentRect(mainRef.current.getBoundingClientRect())
        }
    }, [mainRef, setMainContentRef, setMainContentRect])

    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
        }
    }, [mainRef, setMainContentRef])

    if (mode !== 'full') {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div className="Navigation3000 flex-col" style={theme?.mainStyle}>
                {(mode === 'minimal' || mode === 'zen') && <MinimalNavigation />}
                <main className={mode === 'zen' ? 'p-4' : undefined}>{children}</main>
            </div>
        )
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className={cn(
                'Navigation3000',
                mobileLayout && 'Navigation3000--mobile',
                'Navigation3000--minimal-scene-layout'
            )}
            style={theme?.mainStyle}
        >
            {/* eslint-disable-next-line react/forbid-elements */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:z-top focus:top-4 focus:left-4 focus:p-4 focus:bg-white focus:dark:bg-gray-800 focus:rounded focus:shadow-lg"
                tabIndex={0}
            >
                Skip to content
            </a>

            <ProjectDragAndDropProvider>
                <PanelLayout />

                <FloatingContainerContext.Provider value={mainRef}>
                    <main
                        ref={mainRef}
                        role="main"
                        tabIndex={0}
                        id="main-content"
                        className="@container/main-content bg-surface-tertiary"
                        style={
                            {
                                '--scene-layout-rect-right': mainContentRect?.right + 'px',
                                '--scene-layout-rect-width': mainContentRect?.width + 'px',
                                '--scene-layout-rect-height': mainContentRect?.height + 'px',
                                '--scene-layout-scrollbar-width': mainRef?.current?.clientWidth
                                    ? mainRef.current.clientWidth - (mainContentRect?.width ?? 0) + 'px'
                                    : '0px',
                                '--scene-layout-background': sceneConfig?.canvasBackground
                                    ? 'var(--color-bg-surface-primary)'
                                    : 'var(--color-bg-primary)',
                            } as React.CSSProperties
                        }
                        onScroll={(e) => {
                            if (activeTabId) {
                                setTabScrollDepth(activeTabId, e.currentTarget.scrollTop)
                            }
                        }}
                    >
                        <SceneLayout sceneConfig={sceneConfig}>
                            {(!sceneConfig?.hideBillingNotice || !sceneConfig?.hideProjectNotice) && (
                                <div
                                    className={cn({
                                        'px-4': sceneConfig?.layout === 'app-raw-no-header',
                                    })}
                                >
                                    {!sceneConfig?.hideBillingNotice && <BillingAlertsV2 className="my-0 mb-4" />}
                                    {!sceneConfig?.hideProjectNotice && <ProjectNotice className="my-0 mb-4" />}
                                </div>
                            )}
                            {children}
                        </SceneLayout>
                    </main>
                    <SidePanel />
                </FloatingContainerContext.Provider>
            </ProjectDragAndDropProvider>
        </div>
    )
}
