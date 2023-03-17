import { CommandPalette } from 'lib/components/CommandPalette'
import { ReactNode, useEffect } from 'react'
import { NotebookSideBar } from 'scenes/notebooks/Notebook/NotebookSideBar'
import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'

export function Navigation({ children }: { children: ReactNode }): JSX.Element {
    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    return (
        <div className="Navigation3000">
            <Navbar />
            <Sidebar />
            <main>
                <Breadcrumbs />
                <div className="Navigation3000__scene">
                    <div className="Navigation3000__content">{children}</div>
                    <NotebookSideBar />
                </div>
            </main>

            <CommandPalette />
        </div>
    )
}
