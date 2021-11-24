import React from 'react'
import { Switch } from 'antd'
import { AvailableFeature } from '~/types'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { sceneLogic } from '../../sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { LockOutlined, UnlockOutlined } from '@ant-design/icons'
import { userLogic } from 'scenes/userLogic'

export function AccessControl({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)
    const { hasAvailableFeature } = useValues(userLogic)

    const projectPermissioningEnabled =
        hasAvailableFeature(AvailableFeature.PROJECT_BASED_PERMISSIONING) && currentTeam?.access_control

    return (
        <div>
            <h2 className="subtitle" id="access-control">
                Access Control
            </h2>
            <p>
                {projectPermissioningEnabled ? (
                    <>
                        This project is{' '}
                        <b>
                            <LockOutlined style={{ color: 'var(--warning)', marginRight: 5 }} />
                            private
                        </b>
                        . Only members listed below are allowed to access it.
                    </>
                ) : (
                    <>
                        This project is{' '}
                        <b>
                            <UnlockOutlined style={{ marginRight: 5 }} />
                            open
                        </b>
                        . Any member of the organization can access it. To enable granular access control, make it
                        private.
                    </>
                )}
            </p>
            <Switch
                id="access-control-switch"
                onChange={(checked) => {
                    guardAvailableFeature(
                        AvailableFeature.PROJECT_BASED_PERMISSIONING,
                        'project-based permissioning',
                        'Set permissions granularly for each project. Make sure only the right people have access to protected data.',
                        () => updateCurrentTeam({ access_control: checked })
                    )
                }}
                checked={projectPermissioningEnabled}
                loading={currentOrganizationLoading || currentTeamLoading}
                disabled={isRestricted || !currentOrganization || !currentTeam}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
                htmlFor="access-control-switch"
            >
                Make project private
            </label>
        </div>
    )
}
