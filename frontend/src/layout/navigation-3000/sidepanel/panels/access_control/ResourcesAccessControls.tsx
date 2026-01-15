import { useActions, useAsyncActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { IconEllipsis, IconPencil, IconPlus, IconTrash } from '@posthog/icons'
import {
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTable,
    LemonTabs,
    LemonTag,
    Link,
    Tooltip,
} from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { fullName, toSentenceCase } from 'lib/utils'
import { pluralizeResource } from 'lib/utils/accessControlUtils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    APIScopeObject,
    AccessControlLevel,
    AccessControlTypeMember,
    AvailableFeature,
    OrganizationMemberType,
    RoleType,
} from '~/types'

import { AccessControlLogicProps, accessControlLogic } from './accessControlLogic'
import { resourcesAccessControlLogic } from './resourcesAccessControlLogic'
import { roleAccessControlLogic } from './roleAccessControlLogic'

type ScopeType = 'default' | 'role' | 'member'

type AccessControlRow = {
    id: string
    scopeType: ScopeType
    scopeId: string | null
    scopeLabel: string
    resourceKey: string
    resourceLabel: string
    levels: (AccessControlLevel | null)[]
    isException: boolean
}

type RuleModalState =
    | {
          mode: 'add'
          initialScopeType?: ScopeType
      }
    | {
          mode: 'edit'
          row: AccessControlRow
      }

function SearchableSelect(props: {
    value: string | null
    onChange: (value: string | null) => void
    options: { value: string; label: string }[]
    placeholder: string
    searchPlaceholder: string
    disabled?: boolean
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    const [query, setQuery] = useState('')

    const selectedOption = useMemo(() => {
        return props.options.find((option) => option.value === props.value) ?? null
    }, [props.options, props.value])

    const filteredOptions = useMemo(() => {
        const search = query.trim().toLowerCase()
        if (!search) {
            return props.options
        }
        return props.options.filter((option) => option.label.toLowerCase().includes(search))
    }, [props.options, query])

    return (
        <LemonButtonWithDropdown
            fullWidth
            type="secondary"
            disabled={props.disabled}
            onClick={() => {
                if (!visible) {
                    setQuery('')
                }
            }}
            dropdown={{
                actionable: true,
                placement: 'bottom-start',
                closeOnClickInside: false,
                visible,
                onVisibilityChange: setVisible,
                overlay: (
                    <div className="w-96 p-2 space-y-2">
                        <LemonInput value={query} onChange={setQuery} placeholder={props.searchPlaceholder} autoFocus />
                        <div className="max-h-80 overflow-y-auto">
                            {filteredOptions.length ? (
                                <div className="flex flex-col gap-px">
                                    {filteredOptions.map((option) => (
                                        <LemonButton
                                            key={option.value}
                                            fullWidth
                                            type="tertiary"
                                            onClick={() => {
                                                props.onChange(option.value)
                                                setVisible(false)
                                            }}
                                        >
                                            {option.label}
                                        </LemonButton>
                                    ))}
                                </div>
                            ) : (
                                <div className="text-secondary p-1">No results</div>
                            )}
                        </div>
                    </div>
                ),
            }}
        >
            {selectedOption?.label ?? props.placeholder}
        </LemonButtonWithDropdown>
    )
}

export function ResourcesAccessControls({ projectId }: { projectId: string }): JSX.Element {
    useMountedLogic(membersLogic)
    useMountedLogic(roleAccessControlLogic)
    useMountedLogic(resourcesAccessControlLogic)

    const { currentTeam } = useValues(teamLogic)

    const projectAccessControlProps = useMemo<AccessControlLogicProps>(
        () => ({
            resource: 'project' as APIScopeObject,
            resource_id: projectId,
            title: '',
            description: '',
        }),
        [projectId]
    )

    const {
        accessControlDefault,
        accessControlRoles,
        accessControlMembers,
        availableLevelsWithNone: projectAvailableLevels,
        canEditAccessControls,
        accessControlsLoading,
    } = useValues(accessControlLogic(projectAccessControlProps))

    const {
        resourceAccessControlsLoading,
        availableLevels: resourceAvailableLevels,
        defaultResourceAccessControls,
        memberResourceAccessControls,
        roleResourceAccessControls,
        resources,
        canEditRoleBasedAccessControls,
        hasAvailableFeature,
        roles,
        sortedMembers,
    } = useValues(resourcesAccessControlLogic)

    const { updateAccessControlDefault } = useActions(accessControlLogic(projectAccessControlProps))
    const { updateAccessControlMembers, updateAccessControlRoles } = useAsyncActions(
        accessControlLogic(projectAccessControlProps)
    )

    const { updateResourceAccessControls } = useActions(resourcesAccessControlLogic)

    const canUseRoles = hasAvailableFeature(AvailableFeature.ROLE_BASED_ACCESS)

    const allMembers = useMemo((): OrganizationMemberType[] => {
        return sortedMembers ?? ([] as OrganizationMemberType[])
    }, [sortedMembers])

    const projectResourceLabel = useMemo((): string => {
        const projectName = currentTeam?.name ?? 'Untitled'
        return `Project (${projectName})`
    }, [currentTeam?.name])

    const resourcesWithProject = useMemo((): { key: string; label: string }[] => {
        const resourceOptions = resources.map((resource) => ({
            key: resource,
            label: toSentenceCase(pluralizeResource(resource as APIScopeObject)),
        }))

        return [{ key: 'project', label: projectResourceLabel }, ...resourceOptions]
    }, [projectResourceLabel, resources])

    type AccessControlsTab = 'defaults' | 'roles' | 'members'

    const [activeTab, setActiveTab] = useState<AccessControlsTab>('defaults')

    const [selectedRoleIds, setSelectedRoleIds] = useState<string[]>([])
    const [selectedMemberIds, setSelectedMemberIds] = useState<string[]>([])
    const [selectedResourceKeys, setSelectedResourceKeys] = useState<string[]>([])
    const [selectedRuleLevels, setSelectedRuleLevels] = useState<string[]>([])
    const [searchText, setSearchText] = useState('')

    const [ruleModalState, setRuleModalState] = useState<RuleModalState | null>(null)

    const projectDefaultLevel = (accessControlDefault?.access_level ?? AccessControlLevel.None) as AccessControlLevel

    const projectRoleOverrideByRoleId = useMemo(() => {
        return new Map(accessControlRoles.map((ac) => [ac.role as string, ac.access_level as AccessControlLevel]))
    }, [accessControlRoles])

    const projectMemberOverrideByMemberId = useMemo(() => {
        return new Map(
            (accessControlMembers as (AccessControlTypeMember | any)[])
                .filter((ac): ac is AccessControlTypeMember => !!(ac as AccessControlTypeMember).organization_member)
                .map((ac) => [ac.organization_member as string, ac.access_level as AccessControlLevel])
        )
    }, [accessControlMembers])

    const resourceRoleOverrideByRoleIdAndResourceKey = useMemo(() => {
        const out = new Map<string, Map<string, AccessControlLevel>>()

        for (const entry of roleResourceAccessControls) {
            if (!entry.role) {
                continue
            }
            const mapForRole = new Map<string, AccessControlLevel>()
            for (const [resourceKey, control] of Object.entries(entry.accessControlByResource)) {
                if (control?.access_level !== null && control?.access_level !== undefined) {
                    mapForRole.set(resourceKey, control.access_level as AccessControlLevel)
                }
            }
            out.set(entry.role.id, mapForRole)
        }

        return out
    }, [roleResourceAccessControls])

    const resourceMemberOverrideByMemberIdAndResourceKey = useMemo(() => {
        const out = new Map<string, Map<string, AccessControlLevel>>()

        for (const entry of memberResourceAccessControls) {
            if (!entry.organization_member) {
                continue
            }
            const mapForMember = new Map<string, AccessControlLevel>()
            for (const [resourceKey, control] of Object.entries(entry.accessControlByResource)) {
                if (control?.access_level !== null && control?.access_level !== undefined) {
                    mapForMember.set(resourceKey, control.access_level as AccessControlLevel)
                }
            }
            out.set(entry.organization_member.id, mapForMember)
        }

        return out
    }, [memberResourceAccessControls])

    const allRows = useMemo((): AccessControlRow[] => {
        const rows: AccessControlRow[] = []

        const addRow = (row: Omit<AccessControlRow, 'id'>): void => {
            rows.push({
                ...row,
                id: `${row.scopeType}:${row.scopeId ?? 'default'}:${row.resourceKey}`,
            })
        }

        const addDefaultScopeRows = (): void => {
            addRow({
                scopeType: 'default',
                scopeId: null,
                scopeLabel: 'Default',
                resourceKey: 'project',
                resourceLabel: projectResourceLabel,
                levels: [projectDefaultLevel],
                isException: true,
            })

            for (const resourceKey of resources) {
                const explicitLevel = defaultResourceAccessControls.accessControlByResource[resourceKey]
                    ?.access_level as AccessControlLevel | null | undefined

                if (explicitLevel === null || explicitLevel === undefined) {
                    continue
                }

                addRow({
                    scopeType: 'default',
                    scopeId: null,
                    scopeLabel: 'Default',
                    resourceKey,
                    resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                    levels: [explicitLevel as AccessControlLevel],
                    isException: true,
                })
            }
        }

        const addRoleScopeRows = (): void => {
            if (!canUseRoles) {
                return
            }

            for (const role of roles ?? []) {
                const roleProjectOverride = projectRoleOverrideByRoleId.get(role.id)

                if (roleProjectOverride !== undefined) {
                    addRow({
                        scopeType: 'role',
                        scopeId: role.id,
                        scopeLabel: role.name,
                        resourceKey: 'project',
                        resourceLabel: projectResourceLabel,
                        levels: [roleProjectOverride],
                        isException: true,
                    })
                }

                const overrides = resourceRoleOverrideByRoleIdAndResourceKey.get(role.id)
                if (overrides) {
                    for (const [resourceKey, level] of overrides.entries()) {
                        addRow({
                            scopeType: 'role',
                            scopeId: role.id,
                            scopeLabel: role.name,
                            resourceKey,
                            resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                            levels: [level],
                            isException: true,
                        })
                    }
                }
            }
        }

        const addMemberScopeRows = (): void => {
            for (const member of allMembers) {
                const memberProjectOverride = projectMemberOverrideByMemberId.get(member.id)

                if (memberProjectOverride !== undefined) {
                    addRow({
                        scopeType: 'member',
                        scopeId: member.id,
                        scopeLabel: fullName(member.user),
                        resourceKey: 'project',
                        resourceLabel: projectResourceLabel,
                        levels: [memberProjectOverride],
                        isException: true,
                    })
                }

                const overrides = resourceMemberOverrideByMemberIdAndResourceKey.get(member.id)
                if (overrides) {
                    for (const [resourceKey, level] of overrides.entries()) {
                        addRow({
                            scopeType: 'member',
                            scopeId: member.id,
                            scopeLabel: fullName(member.user),
                            resourceKey,
                            resourceLabel: toSentenceCase(pluralizeResource(resourceKey as APIScopeObject)),
                            levels: [level],
                            isException: true,
                        })
                    }
                }
            }
        }

        addDefaultScopeRows()
        addRoleScopeRows()
        addMemberScopeRows()

        return rows
    }, [
        canUseRoles,
        defaultResourceAccessControls.accessControlByResource,
        allMembers,
        projectDefaultLevel,
        projectMemberOverrideByMemberId,
        projectResourceLabel,
        projectRoleOverrideByRoleId,
        resourceMemberOverrideByMemberIdAndResourceKey,
        resourceRoleOverrideByRoleIdAndResourceKey,
        resources,
        roles,
    ])

    const ruleOptions = useMemo((): { key: string; label: string }[] => {
        const levelSet = new Set<string>()

        for (const level of projectAvailableLevels) {
            levelSet.add(level)
        }
        for (const level of resourceAvailableLevels) {
            levelSet.add(level)
        }
        levelSet.add(AccessControlLevel.None)

        return [...levelSet]
            .sort((a, b) => a.localeCompare(b))
            .map((level) => ({ key: level, label: humanizeLevel(level as AccessControlLevel) }))
    }, [projectAvailableLevels, resourceAvailableLevels])

    const scopedRows = useMemo((): AccessControlRow[] => {
        const scopeType: ScopeType =
            activeTab === 'defaults'
                ? 'default'
                : activeTab === 'roles'
                  ? 'role'
                  : /* activeTab === 'members' */ 'member'

        let rows = allRows.filter((row) => row.scopeType === scopeType)

        if (scopeType === 'role') {
            if (!canUseRoles) {
                return []
            }
            if (selectedRoleIds.length > 0) {
                rows = rows.filter((row) => (row.scopeId ? selectedRoleIds.includes(row.scopeId) : false))
            }
        }

        if (scopeType === 'member') {
            if (selectedMemberIds.length > 0) {
                rows = rows.filter((row) => (row.scopeId ? selectedMemberIds.includes(row.scopeId) : false))
            }
        }

        return rows
    }, [activeTab, allRows, canUseRoles, selectedMemberIds, selectedRoleIds])

    const filteredSortedRows = useMemo((): AccessControlRow[] => {
        const search = searchText.trim().toLowerCase()

        const filtered = scopedRows.filter((row) => {
            if (selectedResourceKeys.length > 0 && !selectedResourceKeys.includes(row.resourceKey)) {
                return false
            }

            if (selectedRuleLevels.length > 0) {
                const ruleKeys = row.levels.map((level) => (level ?? AccessControlLevel.None) as string)
                if (!ruleKeys.some((level) => selectedRuleLevels.includes(level))) {
                    return false
                }
            }

            if (search.length > 0) {
                const levelText = row.levels.map((level) => humanizeLevel(level)).join(' ')
                const haystack = `${row.scopeLabel} ${row.resourceLabel} ${levelText}`.toLowerCase()
                if (!haystack.includes(search)) {
                    return false
                }
            }

            return true
        })

        return [...filtered].sort(sortAccessControlRows)
    }, [scopedRows, searchText, selectedResourceKeys, selectedRuleLevels])

    const canEditAny = !!canEditAccessControls || !!canEditRoleBasedAccessControls

    const columns = useMemo(() => {
        const optionalScopeColumn =
            activeTab === 'roles'
                ? [
                      {
                          title: 'Role',
                          key: 'role',
                          render: function RenderRole(_: any, row: AccessControlRow) {
                              return <span>{row.scopeLabel}</span>
                          },
                      },
                  ]
                : activeTab === 'members'
                  ? [
                        {
                            title: 'Member',
                            key: 'member',
                            render: function RenderMember(_: any, row: AccessControlRow) {
                                return <span>{row.scopeLabel}</span>
                            },
                        },
                    ]
                  : []

        return [
            ...optionalScopeColumn,
            {
                title: 'Feature',
                key: 'resource',
                render: function RenderResource(_: any, row: AccessControlRow) {
                    return <span>{row.resourceLabel}</span>
                },
            },
            {
                title: 'Access',
                key: 'rules',
                render: function RenderRules(_: any, row: AccessControlRow) {
                    const rendered = row.levels.map((level) => ({
                        key: (level ?? AccessControlLevel.None) as string,
                        label: humanizeLevel(level),
                    }))

                    return (
                        <div className="flex gap-2 flex-wrap">
                            {rendered.map(({ key, label }) => (
                                <Tooltip
                                    key={key}
                                    title={describeAccessLevel(key as AccessControlLevel, row.resourceKey)}
                                >
                                    <LemonTag type="default" size="medium" className="px-2">
                                        {label}
                                    </LemonTag>
                                </Tooltip>
                            ))}
                        </div>
                    )
                },
            },
            {
                title: '',
                key: 'actions',
                width: 0,
                align: 'right',
                render: function RenderActions(_: any, row: AccessControlRow) {
                    const isProjectRule = row.resourceKey === 'project'
                    const canEditThisRow = isProjectRule ? canEditAccessControls : canEditRoleBasedAccessControls
                    const disabledReason = !canEditThisRow ? 'You cannot edit this' : undefined

                    return (
                        <LemonButtonWithDropdown
                            size="xsmall"
                            type="tertiary"
                            icon={<IconEllipsis />}
                            disabledReason={disabledReason}
                            dropdown={{
                                actionable: true,
                                placement: 'bottom-end',
                                closeOnClickInside: true,
                                overlay: (
                                    <div className="flex flex-col">
                                        <LemonButton
                                            size="small"
                                            fullWidth
                                            icon={<IconPencil />}
                                            onClick={() => {
                                                setRuleModalState({ mode: 'edit', row })
                                            }}
                                        >
                                            Edit
                                        </LemonButton>
                                        {row.isException &&
                                        !(row.scopeType === 'default' && row.resourceKey === 'project') ? (
                                            <LemonButton
                                                size="small"
                                                fullWidth
                                                status="danger"
                                                icon={<IconTrash />}
                                                onClick={() => confirmDelete(row)}
                                            >
                                                Delete
                                            </LemonButton>
                                        ) : null}
                                    </div>
                                ),
                            }}
                        />
                    )
                },
            },
        ]
    }, [activeTab, canEditAccessControls, canEditRoleBasedAccessControls])

    return (
        <div className="space-y-4">
            <PayGateMini feature={AvailableFeature.ADVANCED_PERMISSIONS}>
                <div className="space-y-4">
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={setActiveTab}
                        tabs={[
                            { key: 'defaults', label: 'Defaults' },
                            {
                                key: 'roles',
                                label: 'Roles',
                                tooltip: !canUseRoles ? 'Requires role-based access' : undefined,
                            },
                            { key: 'members', label: 'Members' },
                        ]}
                    />

                    <div className="flex items-center justify-between gap-2 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                            <LemonInput
                                type="search"
                                className="w-64"
                                value={searchText}
                                onChange={setSearchText}
                                placeholder="Search"
                                size="small"
                            />

                            {activeTab === 'roles' ? (
                                <LemonButtonWithDropdown
                                    type="secondary"
                                    size="small"
                                    disabledReason={!canUseRoles ? 'Roles require an upgrade' : undefined}
                                    dropdown={{
                                        actionable: true,
                                        closeOnClickInside: false,
                                        placement: 'bottom-start',
                                        overlay: (
                                            <MultiSelectFilterDropdown
                                                title="Role"
                                                placeholder="Filter by roles…"
                                                values={selectedRoleIds}
                                                setValues={setSelectedRoleIds}
                                                options={(roles ?? []).map((role) => ({
                                                    key: role.id,
                                                    label: role.name,
                                                }))}
                                            />
                                        ),
                                    }}
                                >
                                    Role{selectedRoleIds.length ? ` (${selectedRoleIds.length})` : ''}
                                </LemonButtonWithDropdown>
                            ) : null}

                            {activeTab === 'members' ? (
                                <LemonButtonWithDropdown
                                    type="secondary"
                                    size="small"
                                    dropdown={{
                                        actionable: true,
                                        closeOnClickInside: false,
                                        placement: 'bottom-start',
                                        overlay: (
                                            <MultiSelectFilterDropdown
                                                title="Member"
                                                placeholder="Filter by members…"
                                                values={selectedMemberIds}
                                                setValues={setSelectedMemberIds}
                                                options={allMembers.map((member) => ({
                                                    key: member.id,
                                                    label: fullName(member.user),
                                                }))}
                                            />
                                        ),
                                    }}
                                >
                                    Member{selectedMemberIds.length ? ` (${selectedMemberIds.length})` : ''}
                                </LemonButtonWithDropdown>
                            ) : null}

                            <LemonButtonWithDropdown
                                type="secondary"
                                size="small"
                                dropdown={{
                                    actionable: true,
                                    closeOnClickInside: false,
                                    placement: 'bottom-start',
                                    overlay: (
                                        <MultiSelectFilterDropdown
                                            title="Feature"
                                            placeholder="Filter by features…"
                                            values={selectedResourceKeys}
                                            setValues={setSelectedResourceKeys}
                                            options={resourcesWithProject.map((r) => ({ key: r.key, label: r.label }))}
                                        />
                                    ),
                                }}
                            >
                                Feature{selectedResourceKeys.length ? ` (${selectedResourceKeys.length})` : ''}
                            </LemonButtonWithDropdown>

                            <LemonButtonWithDropdown
                                type="secondary"
                                size="small"
                                dropdown={{
                                    actionable: true,
                                    closeOnClickInside: false,
                                    placement: 'bottom-start',
                                    overlay: (
                                        <MultiSelectFilterDropdown
                                            title="Access"
                                            placeholder="Filter by access…"
                                            values={selectedRuleLevels}
                                            setValues={setSelectedRuleLevels}
                                            options={ruleOptions}
                                        />
                                    ),
                                }}
                            >
                                Access{selectedRuleLevels.length ? ` (${selectedRuleLevels.length})` : ''}
                            </LemonButtonWithDropdown>
                        </div>

                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconPlus />}
                            onClick={() =>
                                setRuleModalState({
                                    mode: 'add',
                                    initialScopeType:
                                        activeTab === 'defaults'
                                            ? 'default'
                                            : activeTab === 'roles'
                                              ? 'role'
                                              : 'member',
                                })
                            }
                            disabledReason={
                                !canEditAny
                                    ? 'You cannot edit this'
                                    : activeTab === 'roles' && !canUseRoles
                                      ? 'Roles require an upgrade'
                                      : undefined
                            }
                        >
                            Add
                        </LemonButton>
                    </div>

                    <LemonTable
                        columns={columns as any}
                        dataSource={filteredSortedRows}
                        loading={resourceAccessControlsLoading || accessControlsLoading}
                        emptyState="No access control rules match these filters"
                        pagination={{ pageSize: 50, hideOnSinglePage: true }}
                    />
                </div>
            </PayGateMini>

            {ruleModalState ? (
                <RuleModal
                    state={ruleModalState}
                    close={() => setRuleModalState(null)}
                    canUseRoles={canUseRoles}
                    roles={roles ?? []}
                    members={allMembers}
                    resources={resourcesWithProject}
                    projectAvailableLevels={projectAvailableLevels}
                    resourceAvailableLevels={resourceAvailableLevels}
                    canEditAccessControls={canEditAccessControls}
                    canEditRoleBasedAccessControls={canEditRoleBasedAccessControls}
                    onSave={handleSaveRule}
                    loading={resourceAccessControlsLoading || accessControlsLoading}
                />
            ) : null}
        </div>
    )

    function confirmDelete(row: AccessControlRow): void {
        LemonDialog.open({
            title: 'Delete rule',
            description: `Remove this rule for ${row.scopeLabel} → ${row.resourceLabel}?`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => void handleDeleteRule(row),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    async function handleDeleteRule(row: AccessControlRow): Promise<void> {
        const isProjectRule = row.resourceKey === 'project'

        if (isProjectRule) {
            if (row.scopeType === 'role' && row.scopeId) {
                await updateAccessControlRoles([{ role: row.scopeId, level: null }])
                return
            }
            if (row.scopeType === 'member' && row.scopeId) {
                await updateAccessControlMembers([{ member: row.scopeId, level: null }])
                return
            }
            return
        }

        await updateResourceAccessControls(
            [
                {
                    resource: row.resourceKey as any,
                    access_level: null,
                    role: row.scopeType === 'role' ? row.scopeId : null,
                    organization_member: row.scopeType === 'member' ? row.scopeId : null,
                },
            ],
            row.scopeType
        )
    }

    async function handleSaveRule(params: {
        scopeType: ScopeType
        scopeId: string | null
        resourceKey: string
        level: AccessControlLevel
    }): Promise<void> {
        const isProjectRule = params.resourceKey === 'project'

        if (isProjectRule) {
            if (params.scopeType === 'default') {
                updateAccessControlDefault(params.level)
                return
            }
            if (params.scopeType === 'role' && params.scopeId) {
                await updateAccessControlRoles([{ role: params.scopeId, level: params.level }])
                return
            }
            if (params.scopeType === 'member' && params.scopeId) {
                await updateAccessControlMembers([{ member: params.scopeId, level: params.level }])
                return
            }
            return
        }

        await updateResourceAccessControls(
            [
                {
                    resource: params.resourceKey as any,
                    access_level: params.level,
                    role: params.scopeType === 'role' ? params.scopeId : null,
                    organization_member: params.scopeType === 'member' ? params.scopeId : null,
                },
            ],
            params.scopeType
        )
    }
}

function MultiSelectFilterDropdown(props: {
    title: string
    placeholder: string
    options: { key: string; label: string }[]
    values: string[]
    setValues: (values: string[]) => void
}): JSX.Element {
    return (
        <div className="w-96 p-3 space-y-3">
            <div className="flex justify-between items-center">
                <h5 className="mb-0">{props.title}</h5>
                {props.values.length ? (
                    <Link
                        to="#"
                        onClick={(e) => {
                            e.preventDefault()
                            props.setValues([])
                        }}
                    >
                        Clear
                    </Link>
                ) : null}
            </div>
            <LemonInputSelect
                value={props.values}
                onChange={props.setValues}
                mode="multiple"
                placeholder={props.placeholder}
                options={props.options}
            />
        </div>
    )
}

function RuleModal(props: {
    state: RuleModalState
    close: () => void
    canUseRoles: boolean
    roles: RoleType[]
    members: OrganizationMemberType[]
    resources: { key: string; label: string }[]
    projectAvailableLevels: AccessControlLevel[]
    resourceAvailableLevels: AccessControlLevel[]
    canEditAccessControls: boolean | null
    canEditRoleBasedAccessControls: boolean | null
    onSave: (params: {
        scopeType: ScopeType
        scopeId: string | null
        resourceKey: string
        level: AccessControlLevel
    }) => Promise<void>
    loading: boolean
}): JSX.Element {
    const isEditMode = props.state.mode === 'edit'
    const editingRow = props.state.mode === 'edit' ? props.state.row : null

    const initialScopeType = props.state.mode === 'add' ? props.state.initialScopeType : undefined

    const scopeType: ScopeType = editingRow?.scopeType ?? initialScopeType ?? 'default'
    const [scopeId, setScopeId] = useState<string | null>(editingRow?.scopeId ?? null)
    const [resourceKey, setResourceKey] = useState<string>(editingRow?.resourceKey ?? 'project')
    const [level, setLevel] = useState<AccessControlLevel>(
        (editingRow?.levels[0] ?? AccessControlLevel.Viewer) as AccessControlLevel
    )

    const canEditThisRule =
        resourceKey === 'project' ? props.canEditAccessControls : props.canEditRoleBasedAccessControls

    const scopeTargetOptions = useMemo(() => {
        if (scopeType === 'role') {
            return props.roles.map((role) => ({ value: role.id, label: role.name }))
        }
        if (scopeType === 'member') {
            return props.members.map((member) => ({ value: member.id, label: fullName(member.user) }))
        }
        return []
    }, [props.members, props.roles, scopeType])

    const resourceOptions = useMemo(() => {
        return props.resources.map((resource) => ({ value: resource.key, label: resource.label }))
    }, [props.resources])

    const availableLevelsForResource = useMemo((): AccessControlLevel[] => {
        const availableLevels = resourceKey === 'project' ? props.projectAvailableLevels : props.resourceAvailableLevels
        return Array.from(new Set(availableLevels))
    }, [props.projectAvailableLevels, props.resourceAvailableLevels, resourceKey])

    const levelOptions = useMemo(() => {
        return availableLevelsForResource.map((lvl) => ({ value: lvl, label: humanizeLevel(lvl) }))
    }, [availableLevelsForResource])

    useEffect(() => {
        if (props.state.mode === 'edit') {
            return
        }

        if (availableLevelsForResource.includes(level)) {
            return
        }

        const fallbackLevel =
            availableLevelsForResource.find((lvl) => lvl !== AccessControlLevel.None) ??
            availableLevelsForResource[0] ??
            AccessControlLevel.Viewer

        setLevel(fallbackLevel)
    }, [availableLevelsForResource, level, props.state.mode])

    const isValid = scopeType === 'default' || !!scopeId
    const scopeTargetNoun = scopeType === 'role' ? 'role' : 'member'

    const addTitle =
        scopeType === 'default'
            ? 'Add default rule'
            : scopeType === 'role'
              ? 'Add rule for role'
              : 'Add rule for member'

    return (
        <LemonModal
            isOpen={true}
            onClose={props.loading ? undefined : props.close}
            title={isEditMode ? 'Edit rule' : addTitle}
            maxWidth="32rem"
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={props.close} disabled={props.loading}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={
                            !canEditThisRule
                                ? 'You cannot edit this'
                                : !isValid
                                  ? `Please select a ${scopeTargetNoun}`
                                  : undefined
                        }
                        loading={props.loading}
                        onClick={() => {
                            if (!isValid || !canEditThisRule) {
                                return
                            }
                            void props
                                .onSave({
                                    scopeType,
                                    scopeId: scopeType === 'default' ? null : scopeId,
                                    resourceKey,
                                    level,
                                })
                                .then(props.close)
                        }}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                {scopeType !== 'default' ? (
                    <div className="space-y-1">
                        <h5 className="mb-0">{scopeType === 'role' ? 'Role' : 'Member'}</h5>
                        <SearchableSelect
                            value={scopeId}
                            onChange={(value) => setScopeId(value)}
                            options={scopeTargetOptions}
                            placeholder={scopeType === 'role' ? 'Select role…' : 'Select member…'}
                            searchPlaceholder={scopeType === 'role' ? 'Search roles…' : 'Search members…'}
                            disabled={isEditMode}
                        />
                    </div>
                ) : null}

                <div className="space-y-1">
                    <h5 className="mb-0">Feature</h5>
                    <SearchableSelect
                        value={resourceKey}
                        onChange={(value) => setResourceKey(value ?? 'project')}
                        options={resourceOptions}
                        placeholder="Select feature…"
                        searchPlaceholder="Search features…"
                        disabled={isEditMode}
                    />
                </div>

                <div className="space-y-1">
                    <h5 className="mb-0">Rule</h5>
                    <LemonSelect
                        value={level}
                        onChange={(value) => setLevel(value as AccessControlLevel)}
                        options={levelOptions}
                    />
                </div>
            </div>
        </LemonModal>
    )
}

function describeAccessLevel(level: AccessControlLevel | null | undefined, resourceKey: string): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access.'
    }

    if (resourceKey === 'project') {
        if (level === AccessControlLevel.Member) {
            return 'Project member access. Can use the project, but cannot manage project settings.'
        }
        if (level === AccessControlLevel.Admin) {
            return 'Project admin access. Full access, including managing project settings.'
        }
        if (level === AccessControlLevel.Viewer) {
            return 'Read-only access to the project.'
        }
    }

    if (level === AccessControlLevel.Viewer) {
        return 'View-only access. Cannot make changes.'
    }
    if (level === AccessControlLevel.Editor) {
        return 'Edit access. Can create and modify items.'
    }
    if (level === AccessControlLevel.Manager) {
        return 'Manage access. Can configure and manage items.'
    }

    return `${toSentenceCase(level)} access.`
}

function humanizeLevel(level: AccessControlLevel | null | undefined): string {
    if (level === null || level === undefined || level === AccessControlLevel.None) {
        return 'No access'
    }
    return toSentenceCase(level)
}

function sortAccessControlRows(a: AccessControlRow, b: AccessControlRow): number {
    const scopeOrder: Record<ScopeType, number> = { default: 0, role: 1, member: 2 }

    const scopeCmp = scopeOrder[a.scopeType] - scopeOrder[b.scopeType]
    if (scopeCmp !== 0) {
        return scopeCmp
    }

    const labelCmp = a.scopeLabel.localeCompare(b.scopeLabel)
    if (labelCmp !== 0) {
        return labelCmp
    }

    return a.resourceLabel.localeCompare(b.resourceLabel)
}
