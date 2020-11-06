import React from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconBuilding, IconMenu } from './icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { router } from 'kea-router'
import { Button, Dropdown } from 'antd'
import { ProjectOutlined, DownOutlined, ToolOutlined, PlusOutlined } from '@ant-design/icons'

export function TopNavigation(): JSX.Element {
    const { setMenuCollapsed, setChangelogModalOpen, updateCurrentOrganization } = useActions(navigationLogic)
    const { menuCollapsed, systemStatus, updateAvailable, changelogModalOpen } = useValues(navigationLogic)
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { push } = router.actions

    const whoAmIDropdown = (
        <div className="navigation-top-dropdown whoami-dropdown">
            <div className="whoami" style={{ paddingRight: 16, paddingLeft: 16 }}>
                <div className="pp">{user?.name[0].toUpperCase()}</div>
                <div className="details">
                    <span>{user?.email}</span>
                    <span>{user?.organization.name}</span>
                </div>
            </div>
            <div className="text-center">
                <div>
                    <Button className="mt" onClick={() => push('/organization/settings')}>
                        Organization settings
                    </Button>
                </div>
                <div className="mt-05">
                    <a onClick={() => push('/me/settings')}>My account</a>
                </div>
            </div>
            <div className="divider mt-05" />
            <div className="organizations">
                {user?.organizations.map((organization) => {
                    return (
                        <a key={organization.id} onClick={() => updateCurrentOrganization(organization.id)}>
                            <IconBuilding /> {organization.name}
                        </a>
                    )
                })}
            </div>
            <div className="divider mb-05" />
            <div className="text-center">
                <a onClick={logout}>Log out</a>
            </div>
        </div>
    )

    const projectDropdown = (
        <div className="navigation-top-dropdown project-dropdown">
            <div className="dp-title">SELECT A PROJECT</div>
            <div className="projects">
                <a onClick={() => console.log(1)}>
                    <span style={{ flexGrow: 1 }}>Hogflix Web</span>
                    <span
                        className="settings"
                        onClick={(e) => {
                            e.stopPropagation()
                            console.log(2)
                        }}
                    >
                        <ToolOutlined />
                    </span>
                </a>
            </div>
            <div className="divider mt mb-05" />
            <div className="text-center">
                <a onClick={() => {}}>
                    <PlusOutlined /> Create new project
                </a>
            </div>
        </div>
    )

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
                                onClick={() => push('/instance/status')}
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
                <div className="project-chooser">
                    <Dropdown overlay={projectDropdown} trigger={['click']} placement="bottomCenter" visible>
                        <div style={{ height: '100%' }}>
                            <ProjectOutlined className="mr-05" />
                            {user?.team.name} <DownOutlined className="ml-05" />
                        </div>
                    </Dropdown>
                </div>
                <div>
                    <Dropdown overlay={whoAmIDropdown} trigger={['click']}>
                        <div className="whoami cursor-pointer">
                            <div className="pp">{user?.name[0].toUpperCase()}</div>
                            <div className="details hide-lte-lg">
                                <span>{user?.name}</span>
                                <span>{user?.organization.name}</span>
                            </div>
                        </div>
                    </Dropdown>
                </div>
            </div>
            {changelogModalOpen && <ChangelogModal onDismiss={() => setChangelogModalOpen(false)} />}
        </>
    )
}
