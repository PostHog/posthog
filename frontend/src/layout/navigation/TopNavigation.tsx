import React from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconMenu } from './icons'
import { userLogic } from 'scenes/userLogic'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed } = useActions(navigationLogic)
    const { menuCollapsed } = useValues(navigationLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            <div className="navigation-spacer" />
            <div className="navigation-top">
                <div>
                    <div className="hide-gte-lg menu-toggle" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                        <IconMenu />
                    </div>
                </div>
                <div className="middle">Project chooser</div>
                <div>
                    <div className="pp">{user?.name[0].toUpperCase()}</div>
                    <div className="whoami hide-lte-lg">
                        <span>{user?.name}</span>
                        <span>{user?.organization.name}</span>
                    </div>
                </div>
            </div>
        </>
    )
}
