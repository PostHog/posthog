import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { IconHome, IconInfo } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonModal, LemonSelect, Link, Tooltip } from '@posthog/lemon-ui'

import { getAccessControlTooltip } from 'lib/utils/accessControlUtils'

import { APIScopeObject, AccessControlLevel } from '~/types'

import { ScopeIcon } from './ScopeIcon'
import { AccessControlLevelMapping, GroupedAccessControlRulesForm, accessControlsLogic } from './accessControlsLogic'
import { RuleModalState, ScopeType } from './types'

export function GroupedAccessControlRuleModal(props: {
    state: RuleModalState
    close: () => void
    onSave: (params: { scopeType: ScopeType; scopeId: string | null; levels: AccessControlLevelMapping[] }) => void
    resources: { key: APIScopeObject; label: string }[]
    getLevelOptionsForResource: (
        resourceKey: APIScopeObject
    ) => { value: AccessControlLevel; label: string; disabledReason?: string }[]
    loading: boolean
    projectId: string
    canEdit: boolean
    memberIsOrgAdmin: boolean
    memberHasAdminAccess: boolean
    roleHasAdminAccess: boolean
}): JSX.Element | null {
    const logic = accessControlsLogic({ projectId: props.projectId })
    const { groupedRulesForm } = useValues(logic)
    const { setGroupedRulesFormValues } = useActions(logic)

    const editingRow = props.state.row
    const scopeType: ScopeType =
        editingRow.id === 'default' ? 'default' : editingRow.id.startsWith('role:') ? 'role' : 'member'
    const scopeId = editingRow.role.id === 'default' ? null : editingRow.role.id

    useEffect(() => {
        setGroupedRulesFormValues({
            scopeId,
            levels: editingRow.levels,
        })
    }, [editingRow, setGroupedRulesFormValues, scopeId])

    const clearOverrides = (): void => {
        if (props.loading) {
            return
        }

        setGroupedRulesFormValues({
            scopeId,
            levels: groupedRulesForm.levels.filter((l) => l.resourceKey === 'project'),
        })
    }

    const updateLevels = (levels: AccessControlLevelMapping[]): void => {
        setGroupedRulesFormValues({
            scopeId,
            levels,
        })
    }

    const save = (): void => {
        props.onSave({
            scopeType,
            scopeId,
            levels: groupedRulesForm.levels,
        })
    }

    return (
        <LemonModal
            isOpen={true}
            onClose={props.loading ? undefined : props.close}
            title={getGroupedAccessControlRuleModalTitle(scopeType)}
            maxWidth="32rem"
            footer={
                <GroupedAccessControlRuleModalFooter
                    scopeType={scopeType}
                    canEdit={props.canEdit}
                    close={props.close}
                    loading={props.loading}
                    onSave={save}
                />
            }
        >
            <GroupedAccessControlRuleModalContent
                loading={props.loading}
                onClear={clearOverrides}
                resources={props.resources}
                groupedRuleForm={groupedRulesForm}
                onUpdate={updateLevels}
                getLevelOptionsForResource={props.getLevelOptionsForResource}
                canEdit={props.canEdit}
                memberIsOrgAdmin={props.memberIsOrgAdmin}
                memberHasAdminAccess={props.memberHasAdminAccess}
                roleHasAdminAccess={props.roleHasAdminAccess}
            />
        </LemonModal>
    )
}

function GroupedAccessControlRuleModalFooter(props: {
    close: () => void
    loading: boolean
    canEdit: boolean
    onSave: () => void
    scopeType: ScopeType
}): JSX.Element {
    function getDisabledReason(): string | undefined {
        if (!props.canEdit) {
            return 'You cannot edit this rule'
        }

        return undefined
    }

    const disabledReason = getDisabledReason()

    return (
        <div className="flex items-center justify-end gap-2">
            <LemonButton
                type="secondary"
                onClick={props.close}
                disabledReason={props.loading ? 'Cannot close' : undefined}
            >
                Cancel
            </LemonButton>
            <LemonButton type="primary" disabledReason={disabledReason} loading={props.loading} onClick={props.onSave}>
                Save
            </LemonButton>
        </div>
    )
}

function GroupedAccessControlRuleModalContent(props: {
    loading: boolean
    onClear: () => void
    onUpdate: (levels: AccessControlLevelMapping[]) => void
    resources: { key: APIScopeObject; label: string }[]
    groupedRuleForm: GroupedAccessControlRulesForm
    getLevelOptionsForResource: (
        resourceKey: APIScopeObject
    ) => { value: AccessControlLevel; label: string; disabledReason?: string }[]
    canEdit: boolean
    memberIsOrgAdmin: boolean
    memberHasAdminAccess: boolean
    roleHasAdminAccess: boolean
}): JSX.Element {
    const mappedLevels = props.groupedRuleForm.levels.reduce(
        (prev, mapping) => {
            return Object.assign(prev, { [mapping.resourceKey]: mapping.level })
        },
        {} as Record<APIScopeObject, AccessControlLevel>
    )

    const disabledReasonForFeatures = useMemo(() => {
        if (props.loading) {
            return 'Loading...'
        }

        if (!props.canEdit) {
            return 'Cannot edit'
        }

        if (props.memberHasAdminAccess || props.roleHasAdminAccess) {
            return 'Feature overrides do not apply to admins'
        }
    }, [props.loading, props.canEdit, props.memberHasAdminAccess, props.roleHasAdminAccess])

    const disabledReasonForProject = useMemo(() => {
        if (props.loading) {
            return 'Loading...'
        }

        if (!props.canEdit) {
            return 'Cannot edit'
        }

        if (props.memberIsOrgAdmin) {
            return 'Project overrides do not apply to admins'
        }
    }, [props.loading, props.canEdit, props.memberIsOrgAdmin])

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
                        value={mappedLevels['project'] ?? null}
                        disabledReason={disabledReasonForProject}
                        size="small"
                        className="w-36"
                        onChange={(newValue) => {
                            const newLevels = [
                                ...props.groupedRuleForm.levels.filter((mapping) => mapping.resourceKey !== 'project'),
                                ...(newValue ? [{ resourceKey: 'project' as APIScopeObject, level: newValue }] : []),
                            ]
                            props.onUpdate(newLevels)
                        }}
                        options={props.getLevelOptionsForResource('project' as APIScopeObject)}
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
                        className={props.loading ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'}
                    >
                        Clear all
                    </Link>
                </div>

                {props.resources
                    .filter((r) => r.key !== 'project')
                    .map((resource) => {
                        const tooltipText = getAccessControlTooltip(resource.key)
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
                                    <LemonSelect
                                        placeholder="No override"
                                        className="w-36"
                                        size="small"
                                        value={mappedLevels[resource.key] ?? null}
                                        disabledReason={disabledReasonForFeatures}
                                        onChange={(newValue) => {
                                            const newLevels = [
                                                ...props.groupedRuleForm.levels.filter(
                                                    (mapping) => mapping.resourceKey !== resource.key
                                                ),
                                                ...(newValue ? [{ resourceKey: resource.key, level: newValue }] : []),
                                            ]

                                            props.onUpdate(newLevels)
                                        }}
                                        options={[
                                            { value: null, label: 'No override' },
                                            ...props.getLevelOptionsForResource(resource.key),
                                        ]}
                                    />
                                </div>
                            </div>
                        )
                    })}
            </div>
        </div>
    )
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
