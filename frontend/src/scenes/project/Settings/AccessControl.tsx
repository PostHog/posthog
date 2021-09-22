import React from 'react'
import { Switch } from 'antd'
import { AvailableFeature } from '~/types'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { sceneLogic } from '../../sceneLogic'
import { teamLogic } from '../../teamLogic'
import { LockOutlined, UnlockOutlined } from '@ant-design/icons'

export function AccessControl({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    const projectPermissioningEnabled =
        currentOrganization?.available_features.includes(AvailableFeature.PROJECT_BASED_PERMISSIONING) &&
        currentTeam?.project_based_permissioning

    return (
        <div>
            <h2 className="subtitle" id="privacy">
                Privacy settings
            </h2>
            <p>
                {projectPermissioningEnabled ? (
                    <>
                        This project is <b>private</b>. Only members listed below and your organization's administrators
                        and owner will be allowed to access it.
                    </>
                ) : (
                    <>
                        This project is open. Any member in your organization can access it. To enable granular access
                        control, make it private.
                    </>
                )}
            </p>
            <Switch
                // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                id="project-based-permissioning-switch"
                onChange={(checked) => {
                    guardAvailableFeature(
                        AvailableFeature.PROJECT_BASED_PERMISSIONING,
                        'project-based permissioning',
                        'Set permissions granularly for each project. Make sure only the right people have access to protected data.',
                        () => updateCurrentTeam({ project_based_permissioning: checked })
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
                htmlFor="project-based-permissioning-switch"
            >
                {projectPermissioningEnabled ? (
                    <>
                        <LockOutlined style={{ color: 'var(--warning)', marginRight: 4 }} /> This project is{' '}
                        <b>private</b>
                    </>
                ) : (
                    <>
                        <UnlockOutlined style={{ marginRight: 4 }} /> This project is open
                    </>
                )}
                .
            </label>
        </div>
    )
}
