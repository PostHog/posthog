import type { ColumnDef } from '@tanstack/react-table'
import { useActions, useValues } from 'kea'

import { IconHome, IconInfo } from '@posthog/icons'
import {
    DataTable,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Skeleton,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel, AvailableFeature } from '~/types'

import { accessControlsLogic } from './accessControlsLogic'
import { getLevelOptionsForResource } from './helpers'
import { QuillAddLevelMenu } from './QuillAddLevelMenu'
import { QuillLevelSelect } from './QuillLevelSelect'
import { QuillObjectAccessRules } from './QuillObjectAccessRules'
import { QuillPropertyAccessRules } from './QuillPropertyAccessRules'
import { ScopeIcon } from './ScopeIcon'

type ProductRow = { key: APIScopeObject; label: string }

export function QuillAccessControlDefaultSettings({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const { defaults, resourceKeys, loading, accessDetailPanelEnabled, terraformDisabledReason } = useValues(logic)
    const { updateAccessControlDefault, updateResourceAccessControls } = useActions(logic)

    const {
        can_edit: canEdit = false,
        available_project_levels: projectLevels = [],
        available_resource_levels: resourceLevels = [],
    } = defaults ?? {}

    const disabledReason = loading ? 'Loading...' : !canEdit ? (terraformDisabledReason ?? 'Cannot edit') : undefined

    const setResourceDefault = (resource: APIScopeObject, level: AccessControlLevel | null): void => {
        updateResourceAccessControls(
            [{ resource, access_level: level, role: null, organization_member: null }],
            'default'
        )
    }

    const columns: ColumnDef<ProductRow>[] = [
        {
            id: 'label',
            header: 'Product',
            meta: { expand: true },
            enableSorting: false,
            cell: ({ row }) => {
                const tooltipText = getAccessControlTooltip(row.original.key)
                return (
                    <div className="flex items-center gap-2">
                        <span className="flex items-center text-muted-foreground">
                            <ScopeIcon scope={row.original.key} />
                        </span>
                        <Text size="xs" weight="medium" render={<span />}>
                            {row.original.label}
                        </Text>
                        {tooltipText && (
                            <Tooltip>
                                <TooltipTrigger render={<span className="flex items-center text-muted-foreground" />}>
                                    <IconInfo />
                                </TooltipTrigger>
                                <TooltipContent>{tooltipText}</TooltipContent>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            id: 'access',
            header: 'Access',
            meta: { align: 'right' },
            enableSorting: false,
            cell: ({ row }) => {
                const entry = defaults?.resource_access_levels[row.original.key]
                const value = entry?.access_level ?? null
                const options = getLevelOptionsForResource(resourceLevels, {
                    minimum: entry?.minimum ?? null,
                    maximum: entry?.maximum ?? null,
                    inheritedLevel: null,
                    inheritedReason: null,
                    resourceLabel: row.original.label,
                })

                if (value === null) {
                    return (
                        <QuillAddLevelMenu
                            label="Add default"
                            options={options}
                            onSelect={(level) => setResourceDefault(row.original.key, level)}
                            disabledReason={disabledReason}
                        />
                    )
                }

                return (
                    <QuillLevelSelect
                        value={value}
                        options={options}
                        allowNoOverride
                        onChange={(level) => setResourceDefault(row.original.key, level)}
                        disabledReason={disabledReason}
                        className="w-36"
                    />
                )
            },
        },
    ]

    return (
        <PayGateMini feature={AvailableFeature.ACCESS_CONTROL} featureDetail="resource-access-control-default-settings">
            <div className="flex flex-col gap-4">
                <Item variant="outline" size="sm">
                    <ItemMedia>
                        <IconHome />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>Default access to this project</ItemTitle>
                        <ItemDescription>
                            This is the default level of access for everyone in your organization
                        </ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <QuillLevelSelect
                            value={defaults?.project_access_level ?? null}
                            options={getLevelOptionsForResource(projectLevels)}
                            onChange={(newValue) => {
                                updateAccessControlDefault(newValue as AccessControlLevel, 'v2')
                            }}
                            disabledReason={disabledReason}
                            className="w-36"
                        />
                    </ItemActions>
                </Item>

                {loading && !defaults ? (
                    <Skeleton className="h-48 w-full" />
                ) : (
                    <DataTable columns={columns} data={resourceKeys} getRowId={(resource) => resource.key} fullWidth />
                )}

                {accessDetailPanelEnabled && (
                    <>
                        <QuillObjectAccessRules
                            projectId={projectId}
                            scopeType="default"
                            subjectId="default"
                            subjectNoun="project"
                            canEdit={canEdit}
                            cannotEditReason={terraformDisabledReason}
                        />

                        <QuillPropertyAccessRules
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
