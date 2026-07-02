import './Navigation.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { ReactNode, useCallback, useEffect, useRef } from 'react'

import { mcpHintLogic } from 'lib/components/MCPHint/mcpHintLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectDragAndDropProvider } from '~/layout/panel-layout/ProjectTree/ProjectDragAndDropContext'

import { ProjectNotice } from './ProjectNotice'
import { SceneTitlePanelButton } from '../scenes/components/SceneTitleSection'
import { SceneLayout } from '../scenes/SceneLayout'
import { sceneLayoutLogic } from '../scenes/sceneLayoutLogic'
import { MinimalNavigation } from './components/MinimalNavigation'
import { navigationLogic } from './navigationLogic'
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
    const { mobileLayout, mode } = useValues(navigationLogic)
    const mainRef = useRef<HTMLElement>(null)
    const { mainContentRect, isLayoutNavCollapsed, isLayoutPanelVisible, navbarWidth } = useValues(panelLayoutLogic)
    const { setMainContentRef, setMainContentRect } = useActions(panelLayoutLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const { registerScenePanelElement } = useActions(sceneLayoutLogic)
    const { scenePanelIsPresent, scenePanelOpenManual } = useValues(sceneLayoutLogic)
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { sidePanelWidth } = useValues(panelLayoutLogic)

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

    // Set container ref so we can measure the width of the scene layout in logic
    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef)
            // Set main content rect so we can measure the width of the scene layout in logic
            setMainContentRect(mainRef.current.getBoundingClientRect())
        }
    }, [mainRef, setMainContentRef, setMainContentRect])

    // Register `create_user_interview_topic` globally so Max can create user interview
    // topics from any page (including the homepage), not only from the user-interviews
    // scene. The scene wires its own richer `useMaxTool` for the "New topic" button.
    const userInterviewsEnabled = useFeatureFlag('USER_INTERVIEWS')
    useMaxTool({
        identifier: 'create_user_interview_topic',
        active: userInterviewsEnabled,
        context: {},
    })

    const noPaddingScene = sceneConfig?.layout === 'app-raw-no-header' || sceneConfig?.layout === 'app-raw'

    if (mode !== 'full') {
        const showMinimalNavigation = mode === 'minimal' || mode === 'zen'
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div
                className="Navigation flex-col"
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
                        '--left-nav-width': isLayoutNavCollapsed
                            ? 'var(--project-navbar-width-collapsed)'
                            : 'var(--project-navbar-width)',
                    } as React.CSSProperties
                }
            >
                <ProjectDragAndDropProvider>
                    <PanelLayout className="left-nav" />

                    <div
                        className={cn(
                            '@container/main-content-container main-content-container flex overflow-hidden lg:rounded border-t lg:border border-primary relative lg:mr-1 lg:mb-1 lg:mt-1',
                            {
                                'rounded-r-none': sidePanelOpen,
                            }
                        )}
                    >
                        <main
                            ref={mainRef}
                            role="main"
                            tabIndex={0}
                            id="main-content"
                            className={cn(
                                '@container/main-content bg-[var(--scene-layout-background)] overflow-y-auto overflow-x-hidden show-scrollbar-on-hover p-4 pb-0 h-full flex-1 rounded-t focus-visible:outline-none flex flex-col',
                                {
                                    'p-0': noPaddingScene,
                                    'lg:max-w-[calc(100%-var(--side-panel-width))] rounded-r-none': sidePanelOpen,
                                }
                            )}
                        >
                            <SceneLayout sceneConfig={sceneConfig}>
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
                                <SidePanel />
                            </SceneLayout>
                        </main>

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
                </ProjectDragAndDropProvider>
            </div>
        </>
    )
}
