import React, { useState } from 'react'
import './Navigation.scss'
import { useActions, useValues } from 'kea'
import { navigationLogic } from './navigationLogic'
import { IconBuilding, IconMenu } from 'lib/components/icons'
import { userLogic } from 'scenes/userLogic'
import { Badge } from 'lib/components/Badge'
import { ChangelogModal } from '~/layout/ChangelogModal'
import { router } from 'kea-router'
import { Button, Dropdown } from 'antd'
import { ProjectOutlined, DownOutlined, ToolOutlined, PlusOutlined, UpOutlined } from '@ant-design/icons'
import { guardPremiumFeature } from 'scenes/UpgradeModal'
import { sceneLogic } from 'scenes/sceneLogic'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'
import { hot } from 'react-hot-loader/root'

export const TopNavigation = hot(_TopNavigation)
export function _TopNavigation(): JSX.Element {
    const { setMenuCollapsed, setChangelogModalOpen, updateCurrentOrganization, updateCurrentProject } = useActions(
        navigationLogic
    )
    const { menuCollapsed, systemStatus, updateAvailable, changelogModalOpen } = useValues(navigationLogic)
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { showUpgradeModal } = useActions(sceneLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const { push } = router.actions
    const [projectModalShown, setProjectModalShown] = useState(false) // TODO: Move to Kea (using useState for backwards-compatibility with TopSelectors.tsx)
    const [organizationModalShown, setOrganizationModalShown] = useState(false) // TODO: Same as above

    const whoAmIDropdown = (
        <div className="navigation-top-dropdown whoami-dropdown">
            <div className="whoami" style={{ paddingRight: 16, paddingLeft: 16 }}>
                <div className="pp">{user?.name[0]?.toUpperCase()}</div>
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
                <a
                    style={{ color: 'var(--muted)', display: 'flex', justifyContent: 'center' }}
                    onClick={() =>
                        guardPremiumFeature(
                            user,
                            showUpgradeModal,
                            'organizations_projects',
                            'multiple organizations',
                            () => {
                                setOrganizationModalShown(true)
                            },
                            {
                                cloud: false,
                                selfHosted: true,
                            }
                        )
                    }
                >
                    <PlusOutlined style={{ marginRight: 8, fontSize: 18 }} /> New organization
                </a>
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
                {user?.organization.teams.map((team) => {
                    return (
                        <a onClick={() => updateCurrentProject(team.id, '/')} key={team.id}>
                            <span style={{ flexGrow: 1 }}>{team.name}</span>
                            <span
                                className="settings"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    if (team.id === user?.team.id) {
                                        push('/project/settings')
                                    } else {
                                        updateCurrentProject(team.id, '/project/settings')
                                    }
                                }}
                            >
                                <ToolOutlined />
                            </span>
                        </a>
                    )
                })}
            </div>
            <div className="divider mt mb-05" />
            <div className="text-center">
                <a
                    onClick={() =>
                        guardPremiumFeature(
                            user,
                            showUpgradeModal,
                            'organizations_projects',
                            'multiple projects',
                            () => {
                                setProjectModalShown(true)
                            }
                        )
                    }
                >
                    <PlusOutlined /> Create new project
                </a>
            </div>
        </div>
    )

    return (
        <>
            <div className="navigation-spacer" />
            <div className={`navigation-top${sceneConfig.plain ? ' full-width' : ''}`}>
                <div style={{ justifyContent: 'flex-start' }}>
                    <div className="hide-gte-lg menu-toggle" onClick={() => setMenuCollapsed(!menuCollapsed)}>
                        <IconMenu />
                    </div>
                    <div className="hide-lte-lg ml-05">
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
                            icon={<UpOutlined />}
                            onClick={() => setChangelogModalOpen(true)}
                        />
                    </div>
                </div>
                <div className="project-chooser">
                    <Dropdown overlay={projectDropdown} trigger={['click']} placement="bottomCenter">
                        <div style={{ height: '100%' }} className="cursor-pointer flexed">
                            <ProjectOutlined className="mr-05" />
                            {user?.team.name} <DownOutlined className="ml-05" />
                        </div>
                    </Dropdown>
                </div>
                <div>
                    <Dropdown overlay={whoAmIDropdown} trigger={['click']}>
                        <div className="whoami cursor-pointer">
                            <div className="pp">{user?.name[0]?.toUpperCase()}</div>
                            <div className="details hide-lte-lg">
                                <span>{user?.name}</span>
                                <span>{user?.organization.name}</span>
                            </div>
                        </div>
                    </Dropdown>
                </div>
            </div>
            <CreateProjectModal isVisible={projectModalShown} setIsVisible={setProjectModalShown} />
            <CreateOrganizationModal isVisible={organizationModalShown} setIsVisible={setOrganizationModalShown} />
            {changelogModalOpen && <ChangelogModal onDismiss={() => setChangelogModalOpen(false)} />}
        </>
    )
}
