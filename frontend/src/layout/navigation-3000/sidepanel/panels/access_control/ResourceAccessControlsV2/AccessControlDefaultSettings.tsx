import { useActions, useValues } from 'kea'

import { IconHome, IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AvailableFeature } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import { describeAccessControlLevel, getLevelOptionsForResource } from './helpers'
import { ObjectAccessRules } from './ObjectAccessRules'
import { PropertyAccessRules } from './PropertyAccessRules'
import { ScopeIcon } from './ScopeIcon'

/** A level and what it grants, so the menu says who ends up with the access. */
function LevelOptionLabel({ label, description }: { label: string; description: string }): JSX.Element {
    return (
        <div className="flex flex-col gap-[2px] py-1">
            <span>{label}</span>
            <span className="max-w-72 text-xs font-normal text-tertiary text-wrap">{description}</span>
        </div>
    )
}

export function AccessControlDefaultSettings({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const { defaults, resourceKeys, loading, accessDetailPanelEnabled } = useValues(logic)
    const { updateAccessControlDefault, updateResourceAccessControls } = useActions(logic)

    const {
        can_edit: canEdit = false,
        available_project_levels: projectLevels = [],
        available_resource_levels: resourceLevels = [],
    } = defaults ?? {}

    return (
        <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="resource-access-control-default-settings">
            <div className="space-y-4">
                <div className="p-3 bg-surface-primary rounded border border-border flex flex-row gap-4 justify-between items-center">
                    <div>
                        <h4 className="mb-0 font-semibold flex items-center gap-2">
                            <span className="text-lg flex items-center">
                                <IconHome />
                            </span>
                            Default access to this project
                        </h4>
                        <p className="text-xs text-muted-alt mb-0 max-w-md">
                            Everyone in your organization gets this level of access to the project. Roles and
                            person-level rules can change it for specific people.
                        </p>
                    </div>
                    <div className="max-w-sm">
                        <LemonSelect
                            dropdownPlacement="bottom-end"
                            dropdownMatchSelectWidth={false}
                            value={defaults?.project_access_level ?? null}
                            disabledReason={loading ? 'Loading...' : !canEdit ? 'Cannot edit' : undefined}
                            size="small"
                            className="w-36"
                            onChange={(newValue) => {
                                updateAccessControlDefault(newValue as AccessControlLevel, 'v2')
                            }}
                            options={getLevelOptionsForResource(projectLevels).map(({ value, label }) => ({
                                value,
                                label,
                                labelInMenu: (
                                    <LevelOptionLabel
                                        label={label}
                                        description={describeAccessControlLevel(value, 'project')}
                                    />
                                ),
                            }))}
                        />
                    </div>
                </div>

                <LemonTable
                    dataSource={resourceKeys}
                    loading={loading}
                    columns={[
                        {
                            title: 'Tool',
                            key: 'label',
                            render: function RenderTool(_, resource) {
                                const tooltipText = getAccessControlTooltip(resource.key)
                                return (
                                    <div className="font-medium flex items-center gap-2">
                                        <span className="text-lg flex items-center text-muted-alt">
                                            <ScopeIcon scope={resource.key} />
                                        </span>
                                        {resource.label}
                                        {tooltipText && (
                                            <Tooltip title={tooltipText}>
                                                <IconInfo className="text-sm text-muted" />
                                            </Tooltip>
                                        )}
                                    </div>
                                )
                            },
                        },
                        {
                            title: 'Access',
                            key: 'access',
                            align: 'right',
                            render: function RenderAccess(_, resource) {
                                const entry = defaults?.resource_access_levels[resource.key]
                                const value = entry?.access_level ?? null
                                const options = getLevelOptionsForResource(resourceLevels, {
                                    minimum: entry?.minimum ?? null,
                                    maximum: entry?.maximum ?? null,
                                    inheritedLevel: null,
                                    inheritedReason: null,
                                    resourceLabel: resource.label,
                                })

                                if (value === null) {
                                    return (
                                        <LemonDropdown
                                            placement="bottom-end"
                                            overlay={
                                                <div className="flex flex-col">
                                                    {options.map((option) => (
                                                        <LemonButton
                                                            key={option.value}
                                                            size="small"
                                                            className="w-36"
                                                            fullWidth
                                                            disabledReason={option.disabledReason}
                                                            onClick={() => {
                                                                updateResourceAccessControls(
                                                                    [
                                                                        {
                                                                            resource: resource.key,
                                                                            access_level:
                                                                                option.value as AccessControlLevel,
                                                                            role: null,
                                                                            organization_member: null,
                                                                        },
                                                                    ],
                                                                    'default'
                                                                )
                                                            }}
                                                        >
                                                            {option.label}
                                                        </LemonButton>
                                                    ))}
                                                </div>
                                            }
                                        >
                                            <LemonButton
                                                size="small"
                                                type="tertiary"
                                                icon={<IconPlus />}
                                                sideIcon={null}
                                                disabledReason={
                                                    loading ? 'Loading...' : !canEdit ? 'Cannot edit' : undefined
                                                }
                                                className="ml-auto my-0.5 w-36"
                                            >
                                                Add default
                                            </LemonButton>
                                        </LemonDropdown>
                                    )
                                }

                                return (
                                    <LemonSelect
                                        dropdownPlacement="bottom-end"
                                        placeholder="No override"
                                        value={value}
                                        disabledReason={loading ? 'Loading...' : !canEdit ? 'Cannot edit' : undefined}
                                        size="small"
                                        className="ml-auto w-36 my-0.5"
                                        onChange={(newValue) => {
                                            updateResourceAccessControls(
                                                [
                                                    {
                                                        resource: resource.key,
                                                        access_level: newValue as AccessControlLevel | null,
                                                        role: null,
                                                        organization_member: null,
                                                    },
                                                ],
                                                'default'
                                            )
                                        }}
                                        options={[{ value: null, label: 'No override' }, ...options]}
                                    />
                                )
                            },
                        },
                    ]}
                />

                {accessDetailPanelEnabled && (
                    <>
                        <ObjectAccessRules
                            projectId={projectId}
                            scopeType="default"
                            subjectId="default"
                            subjectNoun="project"
                            canEdit={canEdit}
                        />

                        <PropertyAccessRules
                            projectId={projectId}
                            scopeType="default"
                            subjectId="default"
                            subjectNoun="project"
                            canEdit={canEdit}
                        />
                    </>
                )}
            </div>
        </PayGateMini>
    )
}
