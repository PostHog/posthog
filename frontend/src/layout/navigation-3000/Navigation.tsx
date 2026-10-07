import './Navigation.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useLayoutEffect, useRef } from 'react'

import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'
import { TodayShell } from '~/layout/today/TodayShell'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { TodayWarehouseHeader } from '~/layout/today/TodayWarehouseHeader'
import { TodayWarehouseSidebar } from '~/layout/today/TodayWarehouseSidebar'

import { navigationLogic } from '../navigation/navigationLogic'
import { ProjectNotice } from '../navigation/ProjectNotice'
import { SceneTitlePanelButton } from '../scenes/components/SceneTitlePanelButton'
import { SceneLayout } from '../scenes/SceneLayout'
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
    useMountedLogic(mcpHintLogic)

    const { theme } = useValues(themeLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { mode } = useValues(navigation3000Logic)
    const mainRef = useRef<HTMLElement>(null)
    const { mainContentRect, isLayoutNavCollapsed, isLayoutPanelVisible, navbarWidth } = useValues(panelLayoutLogic)
    const { setMainContentRef, setMainContentRect } = useActions(panelLayoutLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const { registerScenePanelElement, registerSceneTakeoverElement } = useActions(sceneLayoutLogic)
    const { scenePanelIsPresent, scenePanelOpenManual, sceneTakeoverActive } = useValues(sceneLayoutLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { sidePanelWidth } = useValues(panelLayoutLogic)
    const {
        leftNavWidth: todayLeftNavWidth,
        todayRailEnabled: todayRail,
        sidebarVisible: todaySidebarVisible,
        phoneLayout: todayPhoneLayout,
        phoneHeaderHidden: todayPhoneHeaderHidden,
        warehouseHeaderShown: todayWarehouseHeaderShown,
        sidebarInContent: todaySidebarInContent,
    } = useValues(todayShellLogic)
    const todayDrawerOpen = todayRail && mobileLayout && todaySidebarVisible
    const todayPhone = todayRail && todayPhoneLayout

    // SceneMenuBar (when enabled) replaces ProjectNotice's role of conveying project-level
    // context above scene content, so we hide the notice for users on the new menu bar.
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const inlinePanelRef = useRef<HTMLDivElement | null>(null)
    const inlinePanelCallbackRef = useCallback(
        (node: HTMLDivElement | null) => {
            inlinePanelRef.current = node
            registerScenePanelElement(node)
        },
        [registerScenePanelElement]
    )

    // SidePanelInfo overrides scenePanelElement while the Info tab is open and
    // clears it on unmount, leaving it null even though Navigation's inline
    // panel div is still in the DOM. Re-register it when the side panel closes.
    useEffect(() => {
        if (!sidePanelOpen && inlinePanelRef.current) {
            registerScenePanelElement(inlinePanelRef.current)
        }
    }, [sidePanelOpen, registerScenePanelElement])

    // Null the registration on Navigation unmount so the detached inline
    // panel div is not pinned by sceneLayoutLogic's reducer. Kept in its own
    // empty-deps effect so it fires only on final unmount, not on every
    // sidePanelOpen toggle (which would briefly blank SceneLayout's portal).
    useEffect(() => {
        return () => {
            registerScenePanelElement(null)
        }
    }, [registerScenePanelElement])

    // Unlike the inline panel above, nothing else ever overrides this registration, so the
    // callback ref's own null call on unmount is enough cleanup.
    const takeoverCallbackRef = useCallback(
        (node: HTMLDivElement | null) => registerSceneTakeoverElement(node),
        [registerSceneTakeoverElement]
    )

    // Set container ref so we can measure the width of the scene layout in logic
    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
            // Set main content rect so we can measure the width of the scene layout in logic
            setMainContentRect(mainRef.current.getBoundingClientRect())
        }
    }, [mainRef, setMainContentRef, setMainContentRect])

    const noPaddingScene = sceneConfig?.layout === 'app-raw-no-header' || sceneConfig?.layout === 'app-raw'

    const todayPhoneBodyClass = todayPhone && mode === 'full'
    useLayoutEffect(() => {
        if (!todayPhoneBodyClass) {
            return
        }
        document.body.classList.add('has-today-phone-layout')
        return () => document.body.classList.remove('has-today-phone-layout')
    }, [todayPhoneBodyClass])

    if (mode !== 'full') {
        const showMinimalNavigation = mode === 'minimal' || mode === 'zen'
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div
                className="Navigation3000 flex-col"
                style={
                    {
                        ...theme?.mainStyle,
                        // The MinimalNavigation bar sits above the scene, so push the
                        // settings scene's viewport-fixed nav down to clear it.
                        ...(showMinimalNavigation && {
                            '--settings-nav-top': 'calc(var(--minimal-navigation-height) + var(--scene-padding))',
                        }),
                    } as React.CSSProperties
                }
            >
                {showMinimalNavigation && <MinimalNavigation />}
                <main
                    className={
                        mode === 'zen'
                            ? 'p-4'
                            : mode === 'embedded'
                              ? '@container/main-content min-h-screen p-4'
                              : undefined
                    }
                >
                    {children}
                </main>
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
                    'app-layout--mobile': (mobileLayout && !todayRail) || todayPhone,
                    'TodayAppLayout scrollbar-thin scrollbar-track-transparent scrollbar-thumb-[var(--color-bg-fill-scroll-thumb)]':
                        todayRail,
                    'TodayAppLayout--phone': todayPhone,
                    'TodayAppLayout--no-phone-header': todayPhoneHeaderHidden,
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
                        // Live navbar width from the resizer drives both the grid's left column
                        // (via --left-nav-width below) and the nav element itself, which reads
                        // --project-navbar-width. Collapsed/mobile fall back to the base default.
                        '--project-navbar-width':
                            !mobileLayout && !isLayoutNavCollapsed ? `${navbarWidth}px` : undefined,
                        '--left-nav-width': todayRail
                            ? `${todayLeftNavWidth}px`
                            : isLayoutNavCollapsed
                              ? 'var(--project-navbar-width-collapsed)'
                              : 'var(--project-navbar-width)',
                    } as React.CSSProperties
                }
            >
                <ProjectDragAndDropProvider>
                    {todayRail ? <TodayShell className="left-nav" /> : <PanelLayout className="left-nav" />}

                    <div
                        className={cn(
                            '@container/main-content-container main-content-container flex overflow-hidden border-primary relative',
                            // Under the Today layout the shell draws the seam against the content in quill's border.
                            // The column is a grid there: the warehouse header spans the top row, and the warehouse sidebar sits under it beside the page.
                            todayRail
                                ? 'grid grid-cols-[auto_minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)]'
                                : [
                                      'lg:rounded border-t lg:border lg:mr-1 lg:mb-1 lg:mt-1',
                                      sidePanelOpen && 'rounded-r-none',
                                  ]
                        )}
                        {...(todayDrawerOpen ? { inert: '' } : {})}
                    >
                        {todayWarehouseHeaderShown && <TodayWarehouseHeader className="col-span-2 row-start-1" />}
                        {todayRail && todaySidebarInContent && todaySidebarVisible && (
                            <TodayWarehouseSidebar className="col-start-1 row-start-2" />
                        )}
                        {/* Same wrapper on every route so main never remounts when the warehouse header or sidebar appears. */}
                        <div
                            className={cn(
                                'relative flex min-h-0 min-w-0 flex-1 overflow-hidden',
                                todayRail && 'col-start-2 row-start-2'
                            )}
                        >
                            <main
                                ref={mainRef}
                                role="main"
                                tabIndex={0}
                                id="main-content"
                                className={cn(
                                    '@container/main-content bg-[var(--scene-layout-background)] overflow-y-auto overflow-x-hidden show-scrollbar-on-hover p-4 pb-0 h-full flex-1 focus-visible:outline-none flex flex-col',
                                    {
                                        // The Today layout's content meets the chrome on straight seams.
                                        'rounded-t': !todayRail,
                                        'p-0': noPaddingScene,
                                        'lg:max-w-[calc(100%-var(--side-panel-width))] rounded-r-none': sidePanelOpen,
                                    }
                                )}
                            >
                                <SceneLayout sceneConfig={sceneConfig}>
                                    {/* While a takeover covers the scene its controls must leave the tab
                                        order and the accessibility tree, or keyboard and screen-reader
                                        users can operate them invisibly. The side panel stays outside the
                                        wrapper: it renders beside the takeover and must stay usable. */}
                                    {/* The attribute rides a spread with the empty-string form: React 18's
                                        types lack `inert`, and its runtime serializes `inert={false}` to a
                                        string, which is still inert (presence-based attribute). */}
                                    <div className="contents" {...(sceneTakeoverActive ? { inert: '' } : {})}>
                                        {!sceneMenuBarEnabled && !sceneConfig?.hideProjectNotice && (
                                            <div
                                                className={cn({
                                                    'px-4 empty:hidden': sceneConfig?.layout === 'app-raw-no-header',
                                                    // Settings scene's nav is viewport-fixed on desktop, so the
                                                    // banner needs to clear it (nav width + column gap) to align
                                                    // with the settings content column.
                                                    'md:ml-[calc(var(--settings-nav-width)+2rem)]':
                                                        activeSceneId === Scene.Settings,
                                                })}
                                            >
                                                <ProjectNotice
                                                    className={cn('my-0 mb-4', {
                                                        'mt-4': noPaddingScene,
                                                    })}
                                                />
                                            </div>
                                        )}
                                        {children}
                                    </div>
                                    <SidePanel />
                                </SceneLayout>
                            </main>

                            {/* Scene takeover host: fullscreen-in-scene surfaces (the email editor)
                                portal here to fill the main well at full height, while the navigation
                                stays visible and the side panel stays usable beside it (z-50 keeps this
                                under the side panel). Mirrors main's max-width shrink so it never sits
                                underneath the open side panel. */}
                            <div
                                ref={takeoverCallbackRef}
                                tabIndex={-1}
                                className={cn(
                                    'absolute inset-0 z-50 bg-[var(--scene-layout-background)] flex flex-col outline-none',
                                    {
                                        hidden: !sceneTakeoverActive,
                                        'lg:max-w-[calc(100%-var(--side-panel-width))]': sidePanelOpen,
                                    }
                                )}
                            />

                            {scenePanelIsPresent && (
                                <>
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
                                            <SceneTitlePanelButton />
                                        </div>
                                        <ScrollableShadows
                                            direction="vertical"
                                            className="grow flex-1"
                                            innerClassName="px-2 py-2 bg-primary"
                                            styledScrollbars
                                        >
                                            <div ref={inlinePanelCallbackRef} />
                                        </ScrollableShadows>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                </ProjectDragAndDropProvider>
            </div>
        </>
    )
}
