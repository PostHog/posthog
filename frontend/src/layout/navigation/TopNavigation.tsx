import React from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconMenu } from './icons'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed } = useActions(navigationLogic)
    const { menuCollapsed } = useValues(navigationLogic)

    return (
        <div className="navigation-top">
            <div>
                <div className="hide-gte-lg menu-toggle" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                    <IconMenu />
                </div>
            </div>
            <div className="middle">Project chooser</div>
            <div>Left</div>
        </div>
    )
}
