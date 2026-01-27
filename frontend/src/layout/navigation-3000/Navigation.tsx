import './Navigation.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { ProjectNotice } from '../navigation/ProjectNotice'
import { navigationLogic } from '../navigation/navigationLogic'
import { SceneLayout } from '../scenes/SceneLayout'
import { ScenePanelContainer } from '../scenes/ScenePanelContainer'
import { SceneTabs } from '../scenes/SceneTabs'
import { SceneTitlePanelButton } from '../scenes/components/SceneTitleSection'
import { sceneLayoutLogic } from '../scenes/sceneLayoutLogic'
import { MinimalNavigation } from './components/MinimalNavigation'
import { navigation3000Logic } from './navigationLogic'
import { SidePanel } from './sidepanel/SidePanel'
import { sidePanelStateLogic } from './sidepanel/sidePanelStateLogic'
import { themeLogic } from './themeLogic'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    useMountedLogic(maxGlobalLogic)
    const { isDev } = useValues(preflightLogic)
    const { theme } = useValues(themeLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { mode } = useValues(navigation3000Logic)
    const mainRef = useRef<HTMLElement>(null)
    const { mainContentRect, isLayoutNavCollapsed, isLayoutPanelVisible } = useValues(panelLayoutLogic)
    const { setMainContentRef, setMainContentRect } = useActions(panelLayoutLogic)
    const { setTabScrollDepth } = useActions(sceneLogic)
    const { activeTabId } = useValues(sceneLogic)
    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const { firstTabIsActive } = useValues(sceneLogic)
    const { sidePanelOpen, sidePanelAvailable } = useValues(sidePanelStateLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    // Legacy: sceneLayoutLogic values for portal-based panel (when flag is off)
    const { registerScenePanelElement } = useActions(sceneLayoutLogic)
    const { scenePanelIsPresent, scenePanelOpenManual } = useValues(sceneLayoutLogic)

    // Set container ref so we can measure the width of the scene layout in logic
    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
            // Set main content rect so we can measure the width of the scene layout in logic
            setMainContentRect(mainRef.current.getBoundingClientRect())
        }
    }, [mainRef, setMainContentRef, setMainContentRect])

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
        <>
            {/* eslint-disable-next-line react/forbid-elements */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:z-top focus:top-4 focus:left-4 focus:p-4 focus:bg-white focus:dark:bg-gray-800 focus:rounded focus:shadow-lg"
                tabIndex={0}
            >
                Skip to content
            </a>
            <div
                className={cn('app-layout bg-surface-tertiary', {
                    'app-layout--mobile': mobileLayout,
                    'app-layout--sidepanel-open': isRemovingSidePanelFlag && sidePanelOpen && sidePanelAvailable,
                    'app-layout--ai-first': isRemovingSidePanelFlag,
                })}
                style={
                    {
                        ...theme?.mainStyle,
                        '--scene-layout-rect-right': mainContentRect?.right + 'px',
                        '--scene-layout-rect-width': mainContentRect?.width + 'px',
                        '--scene-layout-rect-height': mainContentRect?.height + 'px',
                        '--scene-layout-scrollbar-width': mainRef?.current?.clientWidth
                            ? mainRef.current.clientWidth - (mainContentRect?.width ?? 0) + 'px'
                            : '0px',
                        '--scene-layout-background': sceneConfig?.canvasBackground
                            ? 'var(--color-bg-surface-primary)'
                            : 'var(--color-bg-primary)',
                        '--side-panel-width': sidePanelWidth + 'px',
                        '--left-nav-width': isLayoutNavCollapsed
                            ? 'var(--project-navbar-width-collapsed)'
                            : 'var(--project-navbar-width)',
                    } as React.CSSProperties
                }
            >
                <ProjectDragAndDropProvider>
                    <PanelLayout className="left-nav" />

                    <div className="top-nav h-[var(--scene-layout-header-height)] sticky top-0 z-[var(--z-main-nav)] flex justify-center items-start mt-px">
                        <SceneTabs />
                    </div>

                    <div
                        className={cn(
                            '@container/main-content-container main-content-container flex overflow-hidden lg:rounded border-t lg:border border-primary lg:mb-2 relative',
                            {
                                'lg:rounded-tl-none': firstTabIsActive,
                                'lg:mr-2': isRemovingSidePanelFlag,
                            }
                        )}
                    >
                        <main
                            ref={mainRef}
                            role="main"
                            tabIndex={0}
                            id="main-content"
                            className={cn(
                                '@container/main-content bg-[var(--scene-layout-background)] overflow-y-auto overflow-x-hidden show-scrollbar-on-hover p-4 pb-0 h-full flex-1 transition-[width] duration-300 rounded-t',
                                {
                                    'p-0':
                                        sceneConfig?.layout === 'app-raw-no-header' ||
                                        sceneConfig?.layout === 'app-raw',
                                    'rounded-tl-none': firstTabIsActive,
                                    'rounded-tr-none': isRemovingSidePanelFlag && sceneConfig?.scenePanelTabs?.length,
                                }
                            )}
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
                                            'px-4 empty:hidden': sceneConfig?.layout === 'app-raw-no-header',
                                        })}
                                    >
                                        {!sceneConfig?.hideBillingNotice && <BillingAlertsV2 className="my-0 mb-4" />}
                                        {!sceneConfig?.hideProjectNotice && !isDev && (
                                            <ProjectNotice className="my-0 mb-4" />
                                        )}
                                    </div>
                                )}
                                {children}
                            </SceneLayout>
                        </main>

                        {/* New: ScenePanelContainer when flag is on */}
                        {isRemovingSidePanelFlag && <ScenePanelContainer />}

                        {/* Legacy: Portal-based panel when flag is off */}
                        {!isRemovingSidePanelFlag && scenePanelIsPresent && (
                            <div
                                className={cn(
                                    'scene-layout__content-panel starting:w-0 bg-surface-secondary flex flex-col overflow-hidden h-full min-w-0',
                                    'absolute right-0 top-0 @[1200px]/main-content-container:relative @[1200px]/main-content-container:right-auto @[1200px]/main-content-container:top-auto',
                                    {
                                        hidden: !scenePanelOpenManual,
                                        'z-1': isLayoutPanelVisible,
                                    }
                                )}
                            >
                                <div className="h-[50px] flex items-center justify-end gap-2 -mx-2 px-4 py-2 border-b border-primary shrink-0">
                                    <SceneTitlePanelButton inPanel />
                                </div>
                                <ScrollableShadows
                                    direction="vertical"
                                    className="grow flex-1"
                                    innerClassName="px-2 py-2 bg-primary"
                                    styledScrollbars
                                >
                                    <div ref={registerScenePanelElement} />
                                </ScrollableShadows>
                            </div>
                        )}
                    </div>
                    <SidePanel className="right-nav" />
                </ProjectDragAndDropProvider>
            </div>
        </>
    )
}
