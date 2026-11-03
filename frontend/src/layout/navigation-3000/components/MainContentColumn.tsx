import { useActions, useValues } from 'kea'
import { CSSProperties, ReactNode, useEffect, useRef } from 'react'

import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'

import { panelLayoutLogic } from '../../panel-layout/panelLayoutLogic'
import { SceneLayout } from '../../scenes/SceneLayout'
import { sceneLayoutLogic } from '../../scenes/sceneLayoutLogic'
import { ProjectNoticeSlot } from './ProjectNoticeSlot'
import { ScenePanelColumn } from './ScenePanelColumn'
import { SceneTakeoverHost } from './SceneTakeoverHost'

export function MainContentColumn({
    children,
    sceneConfig,
    className,
    inert,
    frame,
    overlay,
    sidePanel,
    sidePanelOverlapsMain = false,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
    className?: string
    inert?: boolean
    frame?: ReactNode
    overlay?: ReactNode
    sidePanel?: ReactNode
    sidePanelOverlapsMain?: boolean
}): JSX.Element {
    const { mainContentRect } = useValues(panelLayoutLogic)
    const { setMainContentRef, setMainContentRect } = useActions(panelLayoutLogic)
    const { sceneTakeoverActive } = useValues(sceneLayoutLogic)

    const mainRef = useRef<HTMLElement>(null)
    const deferSceneMeasurementsDuringResize = sceneConfig?.deferSceneMeasurementsDuringResize ?? false

    useEffect(() => {
        if (mainRef.current) {
            setMainContentRef(mainRef, deferSceneMeasurementsDuringResize)
            setMainContentRect(mainRef.current.getBoundingClientRect())
        }
    }, [mainRef, setMainContentRef, setMainContentRect, deferSceneMeasurementsDuringResize])

    const noPaddingScene = sceneConfig?.layout === 'app-raw-no-header' || sceneConfig?.layout === 'app-raw'

    return (
        <div
            className={cn(
                '@container/main-content-container main-content-container flex overflow-hidden border-primary relative [--left-nav-width:initial] [--project-navbar-width:initial]',
                className
            )}
            // React 18 types lack `inert`, and `inert={false}` still serializes to an inert element.
            {...(inert ? { inert: '' } : {})}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                {
                    '--scene-layout-rect-right': mainContentRect?.right + 'px',
                    '--scene-layout-rect-width': mainContentRect?.width + 'px',
                    '--scene-layout-rect-height': mainContentRect?.height + 'px',
                } as CSSProperties
            }
        >
            {frame}
            <main
                ref={mainRef}
                role="main"
                tabIndex={0}
                id="main-content"
                className={cn(
                    // In Chrome, a rounded scroller that holds many canvases stops painting.
                    '@container/main-content bg-[var(--scene-layout-background)] overflow-y-auto overflow-x-hidden show-scrollbar-on-hover p-4 pb-0 h-full flex-1 focus-visible:outline-none flex flex-col',
                    {
                        'p-0': noPaddingScene,
                        'lg:max-w-[calc(100%-var(--side-panel-width))]': sidePanelOverlapsMain,
                    }
                )}
            >
                <SceneLayout sceneConfig={sceneConfig}>
                    {/* Controls under a takeover leave the tab order and the accessibility tree. The side panel stays usable. */}
                    <div
                        className="contents [--side-panel-width:initial]"
                        {...(sceneTakeoverActive ? { inert: '' } : {})}
                    >
                        <ProjectNoticeSlot sceneConfig={sceneConfig} noPaddingScene={noPaddingScene} />
                        {children}
                    </div>
                    {sidePanel}
                </SceneLayout>
            </main>

            <SceneTakeoverHost sidePanelOverlapsMain={sidePanelOverlapsMain} />
            <ScenePanelColumn />
            {overlay}
        </div>
    )
}
