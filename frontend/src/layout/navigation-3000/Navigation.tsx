import { CommandPalette } from 'lib/components/CommandPalette'
import { useValues } from 'kea'
import { ReactNode, useEffect } from 'react'
import { NotebookSideBar } from 'scenes/notebooks/Notebook/NotebookSideBar'
import { Breadcrumbs } from './components/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'
import { themeLogic } from './themeLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'

export function Navigation({ children }: { children: ReactNode }): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    }, [])

    useEffect(() => {
        document.body.setAttribute('theme', isDarkModeOn ? 'dark' : 'light')
    }, [isDarkModeOn])

    return (
        <div className="Navigation3000">
            <Navbar />
            <Sidebar />
            <main>
                <Breadcrumbs />
                <div className="Navigation3000__scene">
                    <div className="Navigation3000__content">{children}</div>
                    <FlaggedFeature flag={FEATURE_FLAGS.NOTEBOOKS} match>
                        <NotebookSideBar />
                    </FlaggedFeature>
                </div>
            </main>

            <CommandPalette />
        </div>
    )
}
