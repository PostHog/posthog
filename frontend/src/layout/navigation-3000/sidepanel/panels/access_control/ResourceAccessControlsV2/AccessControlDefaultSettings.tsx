import { useActions, useValues } from 'kea'

import { IconHome, IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonSelect, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel, AvailableFeature } from '~/types'

import { ScopeIcon } from './ScopeIcon'
import { accessControlsLogic } from './accessControlsLogic'

export function AccessControlDefaultSettings({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const {
        resourcesWithProject,
        getLevelOptionsForResource,
        allRows,
        loading,
        canEditAccessControls,
        canEditRoleBasedAccessControls,
    } = useValues(logic)
    const { updateAccessControlDefault, updateResourceAccessControls } = useActions(logic)

    const defaultRow = allRows.find((row) => row.id === 'default')
    const mappedLevels: Record<APIScopeObject, AccessControlLevel | null> =
        defaultRow?.levels.reduce(
            (prev, l) => Object.assign(prev, { [l.resourceKey]: l.level }),
            {} as Record<APIScopeObject, AccessControlLevel | null>
        ) || ({} as Record<APIScopeObject, AccessControlLevel | null>)

    return (
        <div className="space-y-4">
            <div className="p-3 bg-surface-primary rounded border border-border flex flex-row justify-between items-center">
                <div>
                    <h4 className="mb-0 font-semibold flex items-center gap-2">
                        <span className="text-lg flex items-center">
                            <IconHome />
                        </span>
                        Default access to this project
                    </h4>
                    <p className="text-xs text-muted-alt mb-0">
                        This is the default level of access for everyone in your organization
                    </p>
                </div>
                <div className="max-w-sm">
                    <LemonSelect
                        dropdownPlacement="bottom-start"
                        value={mappedLevels['project'] ?? null}
                        disabled={loading || !canEditAccessControls}
                        size="small"
                        className="w-36"
                        onChange={(newValue) => {
                            updateAccessControlDefault(newValue as AccessControlLevel)
                        }}
                        options={getLevelOptionsForResource('project' as APIScopeObject)}
                    />
                </div>
            </div>

            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <LemonTable
                    dataSource={resourcesWithProject.filter((r) => r.key !== 'project')}
                    loading={loading}
                    columns={[
                        {
                            title: 'Feature',
                            key: 'label',
                            render: function RenderFeature(_, resource) {
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
                                const canEdit = canEditRoleBasedAccessControls
                                const value = mappedLevels[resource.key] ?? null

                                if (value === null) {
                                    return (
                                        <LemonDropdown
                                            placement="bottom-end"
                                            overlay={
                                                <div className="flex flex-col">
                                                    {getLevelOptionsForResource(resource.key).map((option) => (
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
                                                disabled={loading || !canEdit}
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
                                        disabled={loading || !canEdit}
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
                                        options={[
                                            { value: null, label: 'No override' },
                                            ...getLevelOptionsForResource(resource.key),
                                        ]}
                                    />
                                )
                            },
                        },
                    ]}
                />
            </PayGateMini>
        </div>
    )
}
