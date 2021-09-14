import React from 'react'
import { Switch } from 'antd'
import { AvailableFeature } from '~/types'
import { organizationLogic } from '../../organizationLogic'
import { useActions, useValues } from 'kea'
import { RestrictedComponentProps } from '../../../lib/components/RestrictedArea'
import { sceneLogic } from '../../sceneLogic'
import { Tooltip } from '../../../lib/components/Tooltip'

export function Permissioning({ isRestricted }: RestrictedComponentProps): JSX.Element {
    const { currentOrganization, currentOrganizationLoading } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <div>
            <h2 id="permissioning" className="subtitle">
                Permissioning
            </h2>
            <Tooltip
                title="Per-project access means that organization members below Administrator level by default lack access
                    to projects. Access to each project can then be granted individually only for members who need it."
                placement="topLeft"
            >
                <Switch
                    // @ts-expect-error - id works just fine despite not being in CompoundedComponent
                    id="per-project-access-switch"
                    onChange={(checked) => {
                        guardAvailableFeature(
                            AvailableFeature.PER_PROJECT_ACCESS,
                            'per-project access',
                            'Gain the ability to set permissions granularly inside the organization. Make sure the right people have access to data.',
                            () => updateOrganization({ per_project_access: checked })
                        )
                    }}
                    checked={
                        currentOrganization?.available_features.includes(AvailableFeature.PER_PROJECT_ACCESS) &&
                        currentOrganization?.per_project_access
                    }
                    loading={currentOrganizationLoading}
                    disabled={isRestricted || !currentOrganization}
                />
                <label
                    style={{
                        marginLeft: '10px',
                    }}
                    htmlFor="per-project-access-switch"
                >
                    Per-project access
                </label>
            </Tooltip>
        </div>
    )
}
