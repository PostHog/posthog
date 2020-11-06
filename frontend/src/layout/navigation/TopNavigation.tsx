import React from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconMenu } from './icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { router } from 'kea-router'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed } = useActions(navigationLogic)
    const { menuCollapsed, systemStatus } = useValues(navigationLogic)
    const { user } = useValues(userLogic)

    return (
        <>
            <div className="navigation-spacer" />
            <div className="navigation-top">
                <div>
                    <div className="hide-gte-lg menu-toggle" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                        <IconMenu />
                    </div>
                    <div className="hide-lte-lg">
                        <Badge
                            type={systemStatus ? 'success' : 'danger'}
                            onClick={() => router.actions.push('/instance/status')}
                            tooltip={systemStatus ? 'All systems operational' : 'Potential system issue'}
                        />
                        <Badge className="ml" />
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
