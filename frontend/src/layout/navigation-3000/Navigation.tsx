import { CommandPalette } from 'lib/components/CommandPalette/CommandPalette'
import { useMountedLogic, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'
import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'
import { themeLogic } from './themeLogic'
import { navigation3000Logic } from './navigationLogic'
import clsx from 'clsx'
import { SceneConfig } from 'scenes/sceneTypes'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { SidePanel } from './sidepanel/SidePanel'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    sceneConfig: SceneConfig | null
}): JSX.Element {
    useMountedLogic(themeLogic)
    const { activeNavbarItem, mode } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    return (
        <div className="Navigation3000">
            <Navbar />

            {mode === 'full' && (
                <FlaggedFeature flag={FEATURE_FLAGS.POSTHOG_3000_NAV}>
                    {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
                </FlaggedFeature>
            )}
            <main>
                {mode === 'full' && <Breadcrumbs />}
                <div
                    className={clsx(
                        'Navigation3000__scene',
                        // Hack - once we only have 3000 the "minimal" scenes should become "app-raw"
                        (sceneConfig?.layout === 'app-raw' || mode === 'minimal') && 'Navigation3000__scene--raw'
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
