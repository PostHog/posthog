import React, { Dispatch, SetStateAction, useCallback, useRef, useState } from 'react'
import { useValues, useActions } from 'kea'
import { Alert, Button, Dropdown, Input, Menu, Modal } from 'antd'
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
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { guardPremiumFeature } from 'scenes/UpgradeModal'
import { sceneLogic } from 'scenes/sceneLogic'
import { Link } from 'lib/components/Link'
import api from 'lib/api'

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

function CreateOrganizationModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createOrganization } = useActions(organizationLogic)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const inputRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsVisible(false)
        if (inputRef.current) inputRef.current.setValue('')
    }, [inputRef, setIsVisible])

    return (
        <Modal
            title="Creating an Organization"
            okText="Create Organization"
            cancelText="Cancel"
            onOk={() => {
                const name = inputRef.current?.state.value?.trim()
                if (name) {
                    setErrorMessage(null)
                    createOrganization(name)
                    closeModal()
                } else {
                    setErrorMessage('Your organization needs a name!')
                }
            }}
            onCancel={closeModal}
            visible={isVisible}
        >
            <p>Organizations gather people building products together.</p>
            <Input
                addonBefore="Name"
                ref={inputRef}
                placeholder='for example "Acme Corporation"'
                maxLength={64}
                autoFocus
            />
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginTop: '1rem' }} />}
        </Modal>
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

function CreateProjectModal({
    isVisible,
    setIsVisible,
}: {
    isVisible: boolean
    setIsVisible: Dispatch<SetStateAction<boolean>>
}): JSX.Element {
    const { createTeam } = useActions(teamLogic)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const inputRef = useRef<Input | null>(null)

    const closeModal: () => void = useCallback(() => {
        setErrorMessage(null)
        setIsVisible(false)
        if (inputRef.current) inputRef.current.setValue('')
    }, [inputRef, setIsVisible])

    return (
        <Modal
            title="Creating a Project"
            okText="Create Project"
            cancelText="Cancel"
            onOk={() => {
                const name = inputRef.current?.state.value?.trim()
                if (name) {
                    setErrorMessage(null)
                    createTeam(name)
                    closeModal()
                } else {
                    setErrorMessage('Your project needs a name!')
                }
            }}
            onCancel={closeModal}
            visible={isVisible}
        >
            <p>
                Projects are a way of tracking multiple products under the umbrella of a single organization.
                <br />
                All organization members will be able to access the new project.
            </p>
            <Input
                addonBefore="Name"
                ref={inputRef}
                placeholder='for example "Global Website"'
                maxLength={64}
                autoFocus
            />
            {errorMessage && <Alert message={errorMessage} type="error" style={{ marginTop: '1rem' }} />}
        </Modal>
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
