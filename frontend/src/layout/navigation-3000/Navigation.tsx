import './Navigation.scss'

import clsx from 'clsx'
import { useMountedLogic, useValues } from 'kea'
import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { ReactNode, useEffect } from 'react'
import { SceneConfig } from 'scenes/sceneTypes'

import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
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
    const { activeNavbarItem } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    if (sceneConfig?.layout === 'plain') {
        return <>{children}</>
    }
    return (
        <div className="Navigation3000">
            <Navbar />
            <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000_NAV}>
                {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
            </FlaggedFeature>
            <main>
                <Breadcrumbs />
                <div
                    className={clsx(
                        'Navigation3000__scene',
                        sceneConfig?.layout === 'app-raw' && 'Navigation3000__scene--raw'
                    )}
                >
                    {children}
                </div>
            </main>
            <SidePanel />
            <CommandPalette />
        </div>
    )
}
