import { CommandPalette } from 'lib/components/CommandPalette'
import { useMountedLogic, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'
import { NotebookSideBar } from 'scenes/notebooks/Notebook/NotebookSideBar'
import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'
import { themeLogic } from './themeLogic'
import { navigation3000Logic } from './navigationLogic'
import clsx from 'clsx'
import { sceneLogic } from 'scenes/sceneLogic'

export function Navigation({ children }: { children: ReactNode }): JSX.Element {
    useMountedLogic(themeLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const { activeNavbarItem } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    return (
        <div className="Navigation3000">
            <Navbar />
            {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} navbarItem={activeNavbarItem} />}
            <NotebookSideBar>
                <main>
                    <Breadcrumbs />
                    <div
                        className={clsx(
                            'Navigation3000__scene',
                            !!sceneConfig?.plain && 'Navigation3000__scene--plain'
                        )}
                    >
                        {children}
                    </div>
                </main>
            </NotebookSideBar>

            <CommandPalette />
        </div>
    )
}
