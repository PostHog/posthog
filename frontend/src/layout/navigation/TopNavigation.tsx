import React from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconMenu } from './icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { router } from 'kea-router'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed, setChangelogModalOpen } = useActions(navigationLogic)
    const { menuCollapsed, systemStatus, updateAvailable, changelogModalOpen } = useValues(navigationLogic)
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
                        {!user?.is_multi_tenancy && (
                            <Badge
                                type={systemStatus ? 'success' : 'danger'}
                                onClick={() => router.actions.push('/instance/status')}
                                tooltip={systemStatus ? 'All systems operational' : 'Potential system issue'}
                                className="mr"
                            />
                        )}
                        <Badge
                            type={updateAvailable ? 'warning' : undefined}
                            tooltip={updateAvailable ? 'New version available' : undefined}
                            icon={<></>}
                            onClick={() => setChangelogModalOpen(true)}
                        />
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
            {changelogModalOpen && <ChangelogModal onDismiss={() => setChangelogModalOpen(false)} />}
        </>
    )
}
