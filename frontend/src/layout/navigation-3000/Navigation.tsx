import './Navigation.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { BillingAlertsV2 } from 'lib/components/BillingAlertsV2'
import { CommandBar } from 'lib/components/CommandBar/CommandBar'
import { ReactNode, useRef } from 'react'
import { SceneConfig } from 'scenes/sceneTypes'

import { PanelLayout } from '~/layout/panel-layout/PanelLayout'

import { MaxFloatingInput } from '../../scenes/max/MaxFloatingInput'
import { navigationLogic } from '../navigation/navigationLogic'
import { ProjectNotice } from '../navigation/ProjectNotice'
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

    if (mode !== 'full') {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div className="Navigation3000 flex-col" style={theme?.mainStyle}>
                {mode === 'minimal' ? <MinimalNavigation /> : null}
                <main>{children}</main>
                <MaxFloatingInput />
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

            <PanelLayout mainRef={mainRef} />

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
            <MaxFloatingInput />
        </div>
    )
}
