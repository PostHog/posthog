import type { CellContext, ColumnDef } from '@tanstack/react-table'
import { BindLogic, useActions, useValues } from 'kea'

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

function getDefaultsDisabledReason(
    loading: boolean,
    canEdit: boolean,
    terraformDisabledReason: string | null | undefined
): string | undefined {
    return loading ? 'Loading...' : !canEdit ? (terraformDisabledReason ?? 'Cannot edit') : undefined
}

function ProductCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
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
}

function AccessCell({ row }: CellContext<ProductRow, unknown>): JSX.Element {
    const { defaults, loading, terraformDisabledReason } = useValues(accessControlsLogic)
    const { updateResourceAccessControls } = useActions(accessControlsLogic)

    const { can_edit: canEdit = false, available_resource_levels: resourceLevels = [] } = defaults ?? {}
    const disabledReason = getDefaultsDisabledReason(loading, canEdit, terraformDisabledReason)
    const entry = defaults?.resource_access_levels[row.original.key]
    const value = entry?.access_level ?? null
    const options = getLevelOptionsForResource(resourceLevels, {
        minimum: entry?.minimum ?? null,
        maximum: entry?.maximum ?? null,
        inheritedLevel: null,
        inheritedReason: null,
        resourceLabel: row.original.label,
    })

    const setResourceDefault = (level: AccessControlLevel | null): void => {
        updateResourceAccessControls(
            [{ resource: row.original.key, access_level: level, role: null, organization_member: null }],
            'default'
        )
    }

    if (value === null) {
        return (
            <QuillAddLevelMenu
                label="Add default"
                options={options}
                onSelect={setResourceDefault}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <QuillLevelSelect
            aria-label={`${row.original.label} default access`}
            value={value}
            options={options}
            allowNoOverride
            onChange={setResourceDefault}
            disabledReason={disabledReason}
            className="w-36"
        />
    )
}

// DataTable renders each cell function as a component, so the cells live at module scope and read the logic
// themselves. Rebuilding them on each save would remount the access select and drop keyboard focus.
const COLUMNS: ColumnDef<ProductRow>[] = [
    { id: 'label', header: 'Product', meta: { expand: true }, enableSorting: false, cell: ProductCell },
    { id: 'access', header: 'Access', meta: { align: 'right' }, enableSorting: false, cell: AccessCell },
]

export function QuillAccessControlDefaultSettings({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const { defaults, resourceKeys, loading, accessDetailPanelEnabled, terraformDisabledReason } = useValues(logic)
    const { updateAccessControlDefault } = useActions(logic)

    const { can_edit: canEdit = false, available_project_levels: projectLevels = [] } = defaults ?? {}

    const disabledReason = getDefaultsDisabledReason(loading, canEdit, terraformDisabledReason)

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
                            aria-label="Default access to this project"
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
                    <BindLogic logic={accessControlsLogic} props={{ projectId }}>
                        <DataTable
                            columns={COLUMNS}
                            data={resourceKeys}
                            getRowId={(resource) => resource.key}
                            fullWidth
                        />
                    </BindLogic>
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
