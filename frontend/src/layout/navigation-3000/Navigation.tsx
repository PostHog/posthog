import './Navigation.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { CommandBar } from 'lib/components/CommandBar/CommandBar'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { ReactNode, useRef } from 'react'
import { SceneConfig } from 'scenes/sceneTypes'

import { Navbar } from '~/layout/navigation-3000/components/Navbar'
import { PanelLayout } from '~/layout/panel-layout/PanelLayout'

import { navigationLogic } from '../navigation/navigationLogic'
import { ProjectNotice } from '../navigation/ProjectNotice'
import { MinimalNavigation } from './components/MinimalNavigation'
import { Sidebar } from './components/Sidebar'
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
    const { activeNavbarItem, mode } = useValues(navigation3000Logic)
    const mainRef = useRef<HTMLElement>(null)

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
        <div className={clsx('Navigation3000', mobileLayout && 'Navigation3000--mobile')} style={theme?.mainStyle}>
            {/* eslint-disable-next-line react/forbid-elements */}
            <a
                href="#main-content"
                className="sr-only focus:not-sr-only focus:fixed focus:z-top focus:top-4 focus:left-4 focus:p-4 focus:bg-white focus:dark:bg-gray-800 focus:rounded focus:shadow-lg"
                tabIndex={0}
            >
                Skip to content
            </a>

            <FlaggedFeature
                flag={FEATURE_FLAGS.TREE_VIEW}
                fallback={
                    <FlaggedFeature flag={FEATURE_FLAGS.TREE_VIEW_RELEASE} fallback={<Navbar />}>
                        <PanelLayout mainRef={mainRef} />
                    </FlaggedFeature>
                }
            >
                <PanelLayout mainRef={mainRef} />
            </FlaggedFeature>
            <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000_NAV}>
                {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
            </FlaggedFeature>

            <main ref={mainRef} role="main" tabIndex={0} id="main-content">
                {(sceneConfig?.layout !== 'app-raw-no-header' || mobileLayout) && <TopBar />}
                <div
                    className={clsx(
                        'Navigation3000__scene',
                        // Hack - once we only have 3000 the "minimal" scenes should become "app-raw"
                        sceneConfig?.layout === 'app-raw' && 'Navigation3000__scene--raw',
                        sceneConfig?.layout === 'app-raw-no-header' && 'Navigation3000__scene--raw-no-header'
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
            </main>
            <SidePanel />
            <CommandBar />
        </div>
    )
}
