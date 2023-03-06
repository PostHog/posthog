import { useValues } from 'kea'
import { ReactNode, useEffect } from 'react'
import { Breadcrumbs } from '~/layout/navigation/Breadcrumbs/Breadcrumbs'
import { Navbar } from './components/Navbar'
import { Sidebar } from './components/Sidebar'
import './Navigation.scss'
import { themeLogic } from './themeLogic'

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
                {children}
            </main>
        </div>
    )
}
