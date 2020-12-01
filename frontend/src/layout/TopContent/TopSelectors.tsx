// DEPRECATED in favor of TopNavigation.tsx & navigationLogic.ts
import React, { useState } from 'react'
import { useValues, useActions } from 'kea'
import { Button, Dropdown, Menu } from 'antd'
import {
    ProjectOutlined,
    SmileOutlined,
    DeploymentUnitOutlined,
    SettingOutlined,
    LogoutOutlined,
    PlusOutlined,
    EnterOutlined,
} from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'
import { red } from '@ant-design/colors'
import { guardPremiumFeature } from 'scenes/UpgradeModal'
import { sceneLogic } from 'scenes/sceneLogic'
import { Link } from 'lib/components/Link'
import api from 'lib/api'
import { CreateProjectModal } from 'scenes/project/CreateProjectModal'
import { CreateOrganizationModal } from 'scenes/organization/CreateOrganizationModal'

export function User(): JSX.Element {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)

    return (
        <Dropdown
            overlay={
                <Menu>
                    <Menu.Item key="user-email">
                        <Link to="/me/settings" title="My Settings">
                            <SettingOutlined style={{ marginRight: '0.5rem' }} />
                            {user ? user.email : <i>loading</i>}
                        </Link>
                    </Menu.Item>
                    <Menu.Item key="user-organizations">
                        <Organization />
                    </Menu.Item>
                    <Menu.Item key="user-logout">
                        <a href="#" onClick={logout} data-attr="user-options-logout" style={{ color: red.primary }}>
                            <LogoutOutlined color={red.primary} style={{ marginRight: '0.5rem' }} />
                            Logout
                        </a>
                    </Menu.Item>
                </Menu>
            }
        >
            <Button data-attr="user-options-dropdown" icon={<SmileOutlined />} style={{ fontWeight: 500 }}>
                {user ? user.name || user.email : <i>loading</i>}
            </Button>
        </Dropdown>
    )
}

export function Organization(): JSX.Element {
    const { user } = useValues(userLogic)
    const { showUpgradeModal } = useActions(sceneLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    return (
        <>
            <CreateOrganizationModal isVisible={isModalVisible} setIsVisible={setIsModalVisible} />
            <Dropdown
                overlay={
                    <Menu>
                        {user?.organizations.map(
                            (organization) =>
                                organization.id !== user.organization.id && (
                                    <Menu.Item key={organization.id}>
                                        <a
                                            href="#"
                                            onClick={() => {
                                                api.update('api/user', {
                                                    user: { current_organization_id: organization.id },
                                                }).then(() => {
                                                    location.reload()
                                                })
                                            }}
                                        >
                                            <EnterOutlined size={1} style={{ marginRight: '0.5rem' }} />
                                            {organization.name}
                                        </a>
                                    </Menu.Item>
                                )
                        )}
                        <Menu.Item>
                            <a
                                href="#"
                                onClick={() => {
                                    guardPremiumFeature(
                                        user,
                                        showUpgradeModal,
                                        'organizations_projects',
                                        'multiple organizations',
                                        () => {
                                            setIsModalVisible(true)
                                        },
                                        {
                                            cloud: false,
                                            selfHosted: true,
                                        }
                                    )
                                }}
                            >
                                <PlusOutlined size={1} style={{ marginRight: '0.5rem' }} />
                                <i>New Organization</i>
                            </a>
                        </Menu.Item>
                    </Menu>
                }
            >
                <div data-attr="user-organization-dropdown" title="Current Organization">
                    <DeploymentUnitOutlined size={1} style={{ marginRight: '0.5rem' }} />
                    {user ? user.organization.name : <i>loading</i>}
                </div>
            </Dropdown>
        </>
    )
}

export function Projects(): JSX.Element {
    const { user } = useValues(userLogic)
    const { showUpgradeModal } = useActions(sceneLogic)
    const [isModalVisible, setIsModalVisible] = useState(false)

    return (
        <>
            <CreateProjectModal isVisible={isModalVisible} setIsVisible={setIsModalVisible} />
            <Dropdown
                overlay={
                    <Menu>
                        {user?.organization.teams.map(
                            (team) =>
                                user?.team === null ||
                                (team.id !== user?.team.id && (
                                    <Menu.Item key={team.id}>
                                        <a
                                            href="#"
                                            onClick={() => {
                                                api.update('api/user', { user: { current_team_id: team.id } }).then(
                                                    () => {
                                                        location.reload()
                                                    }
                                                )
                                            }}
                                        >
                                            <EnterOutlined size={1} style={{ marginRight: '0.5rem' }} />
                                            {team.name}
                                        </a>
                                    </Menu.Item>
                                ))
                        )}
                        <Menu.Item>
                            <a
                                href="#"
                                onClick={() => {
                                    guardPremiumFeature(
                                        user,
                                        showUpgradeModal,
                                        'organizations_projects',
                                        'multiple projects',
                                        () => {
                                            setIsModalVisible(true)
                                        }
                                    )
                                }}
                            >
                                <PlusOutlined style={{ marginRight: '0.5rem' }} />
                                <i>New Project</i>
                            </a>
                        </Menu.Item>
                    </Menu>
                }
            >
                <Button
                    data-attr="user-project-dropdown"
                    style={{ marginRight: '0.75rem', fontWeight: 500 }}
                    icon={<ProjectOutlined />}
                >
                    {!user ? <i>loading</i> : user.team ? user.team.name : <i>none yet</i>}
                </Button>
            </Dropdown>
        </>
    )
}
