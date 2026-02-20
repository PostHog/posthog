import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconHome, IconInfo, IconPlus } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonModal, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { toSentenceCase } from 'lib/utils'
import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { ScopeIcon } from './ScopeIcon'
import {
    AccessControlLevelMapping,
    GroupedAccessControlRulesForm,
    accessControlsLogic,
    getEntryId,
} from './accessControlsLogic'
import { getLevelOptionsForResource } from './helpers'
import { AccessControlSettingsEntry, RuleModalState, ScopeType } from './types'

type InheritedReason = 'project_default' | 'role_override' | 'organization_admin' | null | undefined

function getInheritedReasonTooltip(reason: InheritedReason): string | undefined {
    switch (reason) {
        case 'project_default':
            return 'Based on project default permissions'
        case 'role_override':
            return 'Based on role permissions'
        default:
            return undefined
    }
}

function getMinLevelDisabledReason(
    level: AccessControlLevel | null | undefined,
    reason: InheritedReason,
    resourceLabel?: string
): string | undefined {
    if (reason === 'organization_admin') {
        return 'User is an organization admin'
    }
    if (level && level !== 'none') {
        switch (reason) {
            case 'project_default':
                return `Project default is ${toSentenceCase(level)}`
            case 'role_override':
                return `User has a role with ${toSentenceCase(level)} access`
        }
    }
    if (level && level !== 'none' && resourceLabel) {
        return `Minimum level for ${resourceLabel} is ${toSentenceCase(level)}`
    }
    return undefined
}

function getProjectDisabledReason(entry: AccessControlSettingsEntry, canEdit: boolean): string | undefined {
    if (!canEdit) {
        return 'Cannot edit'
    }
    if (entry.project.inherited_access_level_reason === 'organization_admin') {
        return 'User is an organization admin'
    }
    return undefined
}

function getFeaturesDisabledReason(
    entry: AccessControlSettingsEntry,
    canEdit: boolean,
    loading: boolean
): string | undefined {
    if (loading) {
        return 'Loading...'
    }
    if (!canEdit) {
        return 'Cannot edit'
    }
    if (entry.project.inherited_access_level_reason === 'organization_admin') {
        return 'User is an organization admin and has access to all features'
    }
    return undefined
}

function getGroupedAccessControlRuleModalTitle(scopeType: ScopeType): string {
    switch (scopeType) {
        case 'default':
            return 'Update default access'
        case 'role':
            return 'Update role access'
        case 'member':
            return 'Update member access'
    }
}

export function GroupedAccessControlRuleModal(props: {
    state: RuleModalState
    close: () => void
    onSave: (params: { scopeType: ScopeType; scopeId: string | null; levels: AccessControlLevelMapping[] }) => void
    loading: boolean
    projectId: string
    canEdit: boolean
}): JSX.Element | null {
    const logic = accessControlsLogic({ projectId: props.projectId })
    const { groupedRulesForm } = useValues(logic)
    const { setGroupedRulesFormValues } = useActions(logic)

    const { scopeType, entry } = props.state
    const scopeId = getEntryId(entry)

    useEffect(() => {
        // Initialize form with effective levels
        const levels: AccessControlLevelMapping[] = []
        if (entry.project.effective_access_level) {
            levels.push({
                resourceKey: 'project' as APIScopeObject,
                level: entry.project.effective_access_level,
            })
        }
        for (const [resource, resourceEntry] of Object.entries(entry.resources)) {
            if (resourceEntry.effective_access_level) {
                levels.push({
                    resourceKey: resource as APIScopeObject,
                    level: resourceEntry.effective_access_level,
                })
            }
        }
        setGroupedRulesFormValues({ scopeId, levels })
    }, [entry, setGroupedRulesFormValues, scopeId])

    const clearOverrides = (): void => {
        if (props.loading) {
            return
        }
        // Reset all resources to their inherited levels (clearing explicit overrides)
        const levels: AccessControlLevelMapping[] = []
        // Keep project level as is
        const projectLevel = groupedRulesForm.levels.find((l) => l.resourceKey === 'project')
        if (projectLevel) {
            levels.push(projectLevel)
        }
        // Reset resources to inherited levels
        for (const [resource, resourceEntry] of Object.entries(entry.resources)) {
            if (resourceEntry.inherited_access_level) {
                levels.push({
                    resourceKey: resource as APIScopeObject,
                    level: resourceEntry.inherited_access_level,
                })
            }
        }
        setGroupedRulesFormValues({ scopeId, levels })
    }

    const updateLevels = (levels: AccessControlLevelMapping[]): void => {
        setGroupedRulesFormValues({ scopeId, levels })
    }

    const save = (): void => {
        props.onSave({ scopeType, scopeId, levels: groupedRulesForm.levels })
    }

    return (
        <LemonModal
            isOpen={true}
            onClose={props.loading ? undefined : props.close}
            title={getGroupedAccessControlRuleModalTitle(scopeType)}
            maxWidth="32rem"
            footer={
                <GroupedAccessControlRuleModalFooter
                    close={props.close}
                    loading={props.loading}
                    canEdit={props.canEdit}
                    onSave={save}
                />
            }
        >
            <GroupedAccessControlRuleModalContent
                entry={entry}
                groupedRuleForm={groupedRulesForm}
                onUpdate={updateLevels}
                onClear={clearOverrides}
                loading={props.loading}
                canEdit={props.canEdit}
                projectId={props.projectId}
            />
        </LemonModal>
    )
}

function GroupedAccessControlRuleModalFooter(props: {
    close: () => void
    loading: boolean
    canEdit: boolean
    onSave: () => void
}): JSX.Element {
    return (
        <div className="flex items-center justify-end gap-2">
            <LemonButton
                type="secondary"
                onClick={props.close}
                disabledReason={props.loading ? 'Cannot close' : undefined}
            >
                Cancel
            </LemonButton>
            <LemonButton
                type="primary"
                disabledReason={!props.canEdit ? 'You cannot edit this rule' : undefined}
                loading={props.loading}
                onClick={props.onSave}
            >
                Save
            </LemonButton>
        </div>
    )
}

function GroupedAccessControlRuleModalContent(props: {
    entry: AccessControlSettingsEntry
    groupedRuleForm: GroupedAccessControlRulesForm
    onUpdate: (levels: AccessControlLevelMapping[]) => void
    onClear: () => void
    loading: boolean
    canEdit: boolean
    projectId: string
}): JSX.Element {
    const logic = accessControlsLogic({ projectId: props.projectId })
    const { resourcesWithProject, availableProjectLevels, availableResourceLevels } = useValues(logic)

    const projectDisabledReason = getProjectDisabledReason(props.entry, props.canEdit)
    const featuresDisabledReason = getFeaturesDisabledReason(props.entry, props.canEdit, props.loading)

    // Display the form state value for project
    const formProjectLevel = props.groupedRuleForm.levels.find((l) => l.resourceKey === 'project')?.level
    const displayedProjectLevel = formProjectLevel ?? props.entry.project.effective_access_level

    // Prevent users from selecting project level lower than inherited level
    const minimumProjectLevel = props.entry.project.inherited_access_level ?? undefined
    const projectInheritedReason = props.entry.project.inherited_access_level_reason
    const isProjectShowingInherited = displayedProjectLevel === minimumProjectLevel && minimumProjectLevel !== null

    return (
        <div className="space-y-4">
            <div className="flex gap-2 items-center justify-between">
                <div className="font-medium flex items-center gap-2">
                    <span className="text-lg flex items-center text-muted-alt">
                        <IconHome />
                    </span>
                    Project access
                </div>
                <div className="min-w-[8rem]">
                    <LemonSelect
                        dropdownPlacement="bottom-end"
                        value={displayedProjectLevel}
                        disabledReason={projectDisabledReason}
                        tooltip={
                            isProjectShowingInherited ? getInheritedReasonTooltip(projectInheritedReason) : undefined
                        }
                        size="small"
                        className="w-36"
                        onChange={(newValue) => {
                            const newLevels = [
                                ...props.groupedRuleForm.levels.filter((mapping) => mapping.resourceKey !== 'project'),
                                ...(newValue ? [{ resourceKey: 'project' as APIScopeObject, level: newValue }] : []),
                            ]
                            props.onUpdate(newLevels)
                        }}
                        options={getLevelOptionsForResource(availableProjectLevels, {
                            minimum: minimumProjectLevel,
                            disabledReason: getMinLevelDisabledReason(minimumProjectLevel, projectInheritedReason),
                        })}
                    />
                </div>
            </div>

            <LemonDivider className="mb-4" />

            <div className="space-y-2">
                <div className="flex items-center justify-between">
                    <h5 className="mb-2">Features</h5>
                    <Link
                        to="#"
                        onClick={(e) => {
                            e.preventDefault()
                            props.onClear()
                        }}
                        className={
                            props.loading || featuresDisabledReason
                                ? 'cursor-not-allowed opacity-50 pointer-events-none'
                                : 'cursor-pointer'
                        }
                    >
                        Clear all
                    </Link>
                </div>

                {resourcesWithProject
                    .filter((r) => r.key !== 'project')
                    .map((resource) => {
                        const tooltipText = getAccessControlTooltip(resource.key)
                        const resourceEntry = props.entry.resources[resource.key]
                        const formEntry = props.groupedRuleForm.levels.find((l) => l.resourceKey === resource.key)
                        const hasFormEntry = formEntry !== undefined
                        const formLevel = formEntry?.level ?? null
                        const displayedResourceLevel = hasFormEntry
                            ? formLevel
                            : (resourceEntry?.effective_access_level ?? null)

                        // The minimum selectable level is the higher of the resource's minimum and the inherited level
                        const inheritedReason = resourceEntry?.inherited_access_level_reason
                        const isOrgAdmin = inheritedReason === 'organization_admin'
                        const inheritedLevel = resourceEntry?.inherited_access_level
                        const resourceMinimum = resourceEntry?.minimum

                        // Org admins have max access, others can't go below inherited level or the resource's minimum
                        const minimumResourceLevel = isOrgAdmin
                            ? (resourceEntry?.effective_access_level ?? undefined)
                            : (inheritedLevel ?? resourceMinimum)

                        const isShowingInherited = displayedResourceLevel === inheritedLevel && inheritedLevel !== null

                        const resourceMinDisabledReason = isOrgAdmin
                            ? 'User is an organization admin'
                            : (getMinLevelDisabledReason(inheritedLevel, inheritedReason) ??
                              getMinLevelDisabledReason(resourceMinimum, null, resource.label))

                        const levelOptions = getLevelOptionsForResource(availableResourceLevels, {
                            minimum: minimumResourceLevel,
                            disabledReason: resourceMinDisabledReason,
                        })

                        const handleLevelChange = (newValue: AccessControlLevel | null): void => {
                            const newLevels: AccessControlLevelMapping[] = [
                                ...props.groupedRuleForm.levels.filter(
                                    (mapping) => mapping.resourceKey !== resource.key
                                ),
                                // Always add the entry (even with null) to track user's explicit choice
                                { resourceKey: resource.key, level: newValue },
                            ]
                            props.onUpdate(newLevels)
                        }

                        return (
                            <div key={resource.key} className="flex gap-2 items-center justify-between">
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
                                <div className="min-w-[8rem]">
                                    {!inheritedLevel &&
                                    ((hasFormEntry && formLevel === null) ||
                                        (!hasFormEntry && resourceEntry?.access_level === null)) ? (
                                        <LemonDropdown
                                            placement="bottom-end"
                                            overlay={
                                                <div className="flex flex-col">
                                                    {levelOptions.map((option) => (
                                                        <LemonButton
                                                            key={option.value}
                                                            size="small"
                                                            className="w-36"
                                                            fullWidth
                                                            disabledReason={option.disabledReason}
                                                            onClick={() => handleLevelChange(option.value)}
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
                                                disabledReason={featuresDisabledReason}
                                                className="ml-auto w-36"
                                            >
                                                Add override
                                            </LemonButton>
                                        </LemonDropdown>
                                    ) : (
                                        <LemonSelect
                                            className="w-36"
                                            size="small"
                                            value={displayedResourceLevel}
                                            disabledReason={featuresDisabledReason}
                                            tooltip={
                                                isShowingInherited
                                                    ? getInheritedReasonTooltip(inheritedReason)
                                                    : undefined
                                            }
                                            renderButtonContent={(leaf) => {
                                                if (isShowingInherited && inheritedLevel) {
                                                    return toSentenceCase(inheritedLevel)
                                                }
                                                return leaf?.label ?? ''
                                            }}
                                            onChange={handleLevelChange}
                                            options={[
                                                // Only show "No override" if there's no inherited level
                                                ...(inheritedLevel
                                                    ? []
                                                    : [
                                                          {
                                                              value: null as AccessControlLevel | null,
                                                              label: 'No override',
                                                          },
                                                      ]),
                                                ...levelOptions,
                                            ]}
                                        />
                                    )}
                                </div>
                            </div>
                        )
                    })}
            </div>
        </div>
    )
}
