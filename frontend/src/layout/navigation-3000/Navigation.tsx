import { CommandPalette } from 'lib/components/CommandPalette'
import { useMountedLogic, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'
import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'
import { themeLogic } from './themeLogic'
import { navigation3000Logic } from './navigationLogic'
import clsx from 'clsx'
import { NotebookPopover } from 'scenes/notebooks/Notebook/NotebookPopover'
import { Scene, SceneConfig } from 'scenes/sceneTypes'

export function Navigation({
    children,
    sceneConfig,
}: {
    children: ReactNode
    scene: Scene | null
    sceneConfig: SceneConfig | null
}): JSX.Element {
    useMountedLogic(themeLogic)
    const { activeNavbarItem } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    return (
        <div className="Navigation3000">
            <Navbar />
            {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
            <NotebookPopover />
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
            <CommandPalette />
        </div>
    )
}
