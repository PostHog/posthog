import './Navigation.scss'

import clsx from 'clsx'
import { useMountedLogic, useValues } from 'kea'
import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { ReactNode, useEffect } from 'react'
import { SceneConfig } from 'scenes/sceneTypes'

import { navigationLogic } from '../navigation/navigationLogic'
import { MinimalNavigation } from './components/MinimalNavigation'
import { Navbar } from './components/Navbar'
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
    useMountedLogic(themeLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { activeNavbarItem, mode } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    if (mode !== 'full') {
        return (
            <div className="Navigation3000 flex-col">
                {mode === 'minimal' ? <MinimalNavigation /> : null}
                <main>{children}</main>
            </div>
        )
    }

    return (
        <div className={clsx('Navigation3000', mobileLayout && 'Navigation3000--mobile')}>
            <Navbar />
            <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000_NAV}>
                {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
            </FlaggedFeature>
            <main>
                <TopBar />
                <div
                    className={clsx(
                        'Navigation3000__scene',
                        // Hack - once we only have 3000 the "minimal" scenes should become "app-raw"
                        sceneConfig?.layout === 'app-raw' && 'Navigation3000__scene--raw'
                    )}
                >
                    {children}
                </div>
            </main>
            {!mobileLayout && <SidePanel />}
            <CommandPalette />
        </div>
    )
}
