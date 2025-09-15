import './Navigation.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { CommandBar } from 'lib/components/CommandBar/CommandBar'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { SceneConfig } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'

import { MaxFloatingInput } from '../../scenes/max/MaxFloatingInput'
import { ProjectNotice } from '../navigation/ProjectNotice'
import { navigationLogic } from '../navigation/navigationLogic'
import { panelLayoutLogic } from '../panel-layout/panelLayoutLogic'
import { SceneLayout } from '../scenes/SceneLayout'
import { MinimalNavigation } from './components/MinimalNavigation'
import { TopBar } from './components/TopBar'
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
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]
    const { currentTeam } = useValues(teamLogic)
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
                {currentTeam ? <MaxFloatingInput /> : null}
            </div>
        )
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className={cn(
                'Navigation3000',
                mobileLayout && 'Navigation3000--mobile',
                newSceneLayout && 'Navigation3000--minimal-scene-layout'
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
                    } as React.CSSProperties
                }
            >
                <FlaggedFeature
                    match={true}
                    flag={FEATURE_FLAGS.NEW_SCENE_LAYOUT}
                    fallback={
                        <>
                            {(sceneConfig?.layout !== 'app-raw-no-header' || mobileLayout) && <TopBar />}
                            <div
                                className={cn(
                                    'Navigation3000__scene',
                                    // Hack - once we only have 3000 the "minimal" scenes should become "app-raw"
                                    sceneConfig?.layout === 'app-raw' && 'Navigation3000__scene--raw',
                                    sceneConfig?.layout === 'app-raw-no-header' &&
                                        'Navigation3000__scene--raw-no-header'
                                )}
                            >
                                {(!sceneConfig?.hideBillingNotice || !sceneConfig?.hideProjectNotice) && (
                                    <div className={sceneConfig?.layout === 'app-raw-no-header' ? 'px-4' : ''}>
                                        {!sceneConfig?.hideBillingNotice && <BillingAlertsV2 />}
                                        {!sceneConfig?.hideProjectNotice && <ProjectNotice />}
                                    </div>
                                )}

                                {children}
                            </div>
                        </>
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
                </FlaggedFeature>
            </main>
            <SidePanel />
            <CommandBar />
            {currentTeam ? <MaxFloatingInput /> : null}
        </div>
    )
}
