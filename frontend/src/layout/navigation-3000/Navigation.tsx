import './Navigation.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { CommandBar } from 'lib/components/CommandBar/CommandBar'
import { FloatingContainerContext } from 'lib/hooks/useFloatingContainerContext'
import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'

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
                {mode === 'minimal' ? <MinimalNavigation /> : null}
                <main>{children}</main>
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

            <PanelLayout />

            <FloatingContainerContext.Provider value={mainRef}>
                <main
                    ref={mainRef}
                    role="main"
                    tabIndex={0}
                    id="main-content"
                    className="@container/main-content"
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
                >
                    <SceneLayout sceneConfig={sceneConfig}>
                        {(!sceneConfig?.hideBillingNotice || !sceneConfig?.hideProjectNotice) && (
                            <div className={sceneConfig?.layout === 'app-raw-no-header' ? 'px-4' : ''}>
                                {!sceneConfig?.hideBillingNotice && <BillingAlertsV2 className="my-0 mb-4" />}
                                {!sceneConfig?.hideProjectNotice && <ProjectNotice className="my-0 mb-4" />}
                            </div>
                        )}
                        {children}
                    </SceneLayout>
                </main>
                <SidePanel />
                <CommandBar />
            </FloatingContainerContext.Provider>
        </div>
    )
}
