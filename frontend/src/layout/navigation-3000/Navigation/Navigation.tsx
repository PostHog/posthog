import { ReactNode, useEffect } from 'react'
import { Breadcrumbs } from '~/layout/navigation/Breadcrumbs/Breadcrumbs'
import { Navbar } from '../Navbar/Navbar'
import './Navigation.scss'

export function Navigation({ children }: { children: ReactNode }): JSX.Element {
    useEffect(() => {
        // FIXME: Include debug notice in a non-obstructing way
        document.getElementById('bottom-notice')?.remove()
    })

    return (
        <div className="Navigation3000">
            <Navbar />
            <main>
                <Breadcrumbs />
                {children}
            </main>
        </div>
    )
}
