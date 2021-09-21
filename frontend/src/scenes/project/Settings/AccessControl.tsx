import React from 'react'
import { Switch } from 'antd'
import { AvailableFeature } from '~/types'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { sceneLogic } from '../../sceneLogic'
import { teamLogic } from '../../teamLogic'

export function AccessControl({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <div>
            <h2 className="subtitle" id="access-control">
                Access Control
            </h2>
            <p>
                By default <i>all</i> members of the organizations have access to the project.
                <br />
                <b>With project-based permissioning only administrator and above have such implicit access.</b>
                <br />
                Lower-level members need to be added explicitly. At the same time you can grant them project-specific
                access <i>higher</i> than their organization-wide level.
            </p>
            <Switch
                // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                id="project-based-permissioning-switch"
                onChange={(checked) => {
                    guardAvailableFeature(
                        AvailableFeature.PROJECT_BASED_PERMISSIONING,
                        'project-based permissioning',
                        'Set permissions granularly for each project. Make sure the right people have access to data.',
                        () => updateCurrentTeam({ project_based_permissioning: checked })
                    )
                }}
                checked={
                    currentOrganization?.available_features.includes(AvailableFeature.PROJECT_BASED_PERMISSIONING) &&
                    currentTeam?.project_based_permissioning
                }
                loading={currentOrganizationLoading || currentTeamLoading}
                disabled={isRestricted || !currentOrganization || !currentTeam}
            />
            <label
                style={{
                    marginLeft: '10px',
                }}
                htmlFor="project-based-permissioning-switch"
            >
                Enable project-based permissioning
            </label>
        </div>
    )
}
