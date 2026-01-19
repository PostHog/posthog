import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { fullName } from 'lib/utils'

import { AccessControlLevel, OrganizationMemberType, RoleType } from '~/types'

import { SearchableSelect } from './SearchableSelect'
import { humanizeAccessControlLevel } from './helpers'
import { RuleModalState, ScopeType } from './types'

export function AccessControlRuleModal(props: {
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
    }) => void
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
        return availableLevelsForResource.map((lvl) => ({ value: lvl, label: humanizeAccessControlLevel(lvl) }))
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

    return (
        <LemonModal
            isOpen={true}
            onClose={props.loading ? undefined : props.close}
            title={isEditMode ? 'Edit rule' : getAddAccessControlRuleModalTitle(scopeType)}
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
                            props.onSave({
                                scopeType,
                                scopeId: scopeType === 'default' ? null : scopeId,
                                resourceKey,
                                level,
                            })
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
                            disabledReason={isEditMode ? 'Cannot edit' : undefined}
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
                        disabledReason={isEditMode ? 'Cannot edit' : undefined}
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

function getAddAccessControlRuleModalTitle(scopeType: ScopeType): string {
    switch (scopeType) {
        case 'default':
            return 'Add default rule'
        case 'role':
            return 'Add rule for role'
        case 'member':
            return 'Add rule for member'
    }
}
