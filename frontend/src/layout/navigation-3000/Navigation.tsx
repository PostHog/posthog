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

export function Navigation({ children }: { children: ReactNode }): JSX.Element {
    useMountedLogic(themeLogic)
    const { activeNavbarItem } = useValues(navigation3000Logic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    return (
        <div className="Navigation3000">
            <Navbar />
            {activeNavbarItem && <Sidebar key={activeNavbarItem.identifier} />}
            <NotebookSideBar>
                <main>
                    <Breadcrumbs />
                    <div className="Navigation3000__scene">
                        <div className="Navigation3000__content">{children}</div>
                    </div>
                </main>
            </NotebookSideBar>

            <CommandPalette />
        </div>
    )
}
