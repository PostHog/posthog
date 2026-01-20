import { useEffect, useMemo, useState } from 'react'

import { LemonButton, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { capitalizeFirstLetter, fullName, wordPluralize } from 'lib/utils'

import { APIScopeObject, AccessControlLevel, OrganizationMemberType, RoleType } from '~/types'

import { SearchableSelect } from './SearchableSelect'
import { getScopeTypeNoun, humanizeAccessControlLevel } from './helpers'
import { RuleModalState, ScopeType } from './types'

export function AccessControlRuleModal(props: {
    state: RuleModalState
    close: () => void
    canUseRoles: boolean
    roles: RoleType[]
    members: OrganizationMemberType[]
    resources: { key: APIScopeObject; label: string }[]
    projectAvailableLevels: AccessControlLevel[]
    resourceAvailableLevels: AccessControlLevel[]
    canEditAccessControls: boolean
    canEditRoleBasedAccessControls: boolean
    onSave: (params: {
        scopeType: ScopeType
        scopeId: string | null
        resourceKey: APIScopeObject
        level: AccessControlLevel
    }) => void
    loading: boolean
}): JSX.Element {
    const editingRow = props.state.mode === 'edit' ? props.state.row : null
    const initialScopeType = props.state.mode === 'add' ? props.state.initialScopeType : undefined
    const scopeType: ScopeType = editingRow?.scopeType ?? initialScopeType ?? 'default'

    const [scopeId, setScopeId] = useState<string | null>(editingRow?.scopeId ?? null)
    const [resourceKey, setResourceKey] = useState<APIScopeObject>(editingRow?.resourceKey ?? 'project')
    const [level, setLevel] = useState<AccessControlLevel>(editingRow?.level ?? AccessControlLevel.Viewer)
    const canEdit = resourceKey === 'project' ? props.canEditAccessControls : props.canEditRoleBasedAccessControls

    const availableLevelsForResource = useMemo((): AccessControlLevel[] => {
        const availableLevels = resourceKey === 'project' ? props.projectAvailableLevels : props.resourceAvailableLevels
        return Array.from(new Set(availableLevels))
    }, [props.projectAvailableLevels, props.resourceAvailableLevels, resourceKey])

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

    return (
        <LemonModal
            isOpen={true}
            onClose={props.loading ? undefined : props.close}
            title={
                props.state.mode === 'edit'
                    ? getEditAccessControlRuleModalTitle(scopeType)
                    : getAddAccessControlRuleModalTitle(scopeType)
            }
            maxWidth="32rem"
            footer={
                <AccessControlRuleModalFooter
                    scopeType={scopeType}
                    canEdit={canEdit ?? false}
                    close={props.close}
                    isValid={isValid}
                    loading={props.loading}
                    onSave={() => {
                        if (!isValid || !canEdit) {
                            return
                        }
                        props.onSave({
                            scopeType,
                            scopeId: scopeType === 'default' ? null : scopeId,
                            resourceKey,
                            level,
                        })
                    }}
                />
            }
        >
            <AccessControlRuleModalContent
                state={props.state}
                level={level}
                setLevel={setLevel}
                resourceKey={resourceKey}
                setResourceKey={setResourceKey}
                scopeId={scopeId}
                setScopeId={setScopeId}
                scopeType={scopeType}
                roles={props.roles}
                members={props.members}
                resources={props.resources}
                availableLevels={availableLevelsForResource}
            />
        </LemonModal>
    )
}

function AccessControlRuleModalFooter(props: {
    close: () => void
    loading: boolean
    canEdit: boolean
    isValid: boolean
    onSave: () => void
    scopeType: ScopeType
}): JSX.Element {
    function getDisabledReason(): string | undefined {
        if (!props.canEdit) {
            return 'You cannot edit this rule'
        }

        if (!props.isValid) {
            return `Please select a ${getScopeTypeNoun(props.scopeType)}`
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

function AccessControlRuleModalContent(props: {
    state: RuleModalState
    scopeType: ScopeType
    scopeId: string | null
    setScopeId: React.Dispatch<React.SetStateAction<string | null>>
    resourceKey: APIScopeObject
    setResourceKey: React.Dispatch<React.SetStateAction<APIScopeObject>>
    level: AccessControlLevel
    setLevel: React.Dispatch<React.SetStateAction<AccessControlLevel>>
    roles: RoleType[]
    members: OrganizationMemberType[]
    resources: { key: APIScopeObject; label: string }[]
    availableLevels: AccessControlLevel[]
}): JSX.Element {
    const scopeTypeNoun = getScopeTypeNoun(props.scopeType)

    const scopeTargetOptions = useMemo(() => {
        if (props.scopeType === 'role') {
            return props.roles.map((role) => ({ value: role.id, label: role.name }))
        }
        if (props.scopeType === 'member') {
            return props.members.map((member) => ({ value: member.id, label: fullName(member.user) }))
        }
        return []
    }, [props.members, props.roles, props.scopeType])

    const resourceOptions = useMemo(() => {
        return props.resources.map((resource) => ({ value: resource.key, label: resource.label }))
    }, [props.resources])

    const levelOptions = useMemo(() => {
        return props.availableLevels.map((lvl) => ({ value: lvl, label: humanizeAccessControlLevel(lvl) }))
    }, [props.availableLevels])

    return (
        <div className="space-y-4">
            {props.scopeType !== 'default' && (
                <div className="space-y-1">
                    <h5 className="mb-0">{capitalizeFirstLetter(scopeTypeNoun)}</h5>
                    <SearchableSelect
                        value={props.scopeId}
                        onChange={props.setScopeId}
                        options={scopeTargetOptions}
                        placeholder={`Select ${scopeTypeNoun}…`}
                        searchPlaceholder={`Search ${wordPluralize(scopeTypeNoun)}…`}
                        disabledReason={
                            props.state.mode === 'edit' ? `Cannot change ${scopeTypeNoun} for existing rule` : undefined
                        }
                    />
                </div>
            )}

            <div className="space-y-1">
                <h5 className="mb-0">Feature</h5>
                <SearchableSelect
                    value={props.resourceKey}
                    onChange={(value) => props.setResourceKey((value ?? 'project') as APIScopeObject)}
                    options={resourceOptions}
                    placeholder="Select feature…"
                    searchPlaceholder="Search features…"
                    disabledReason={props.state.mode === 'edit' ? 'Cannot change feature for existing rule' : undefined}
                />
            </div>

            <div className="space-y-1">
                <h5 className="mb-0">Rule</h5>
                <LemonSelect value={props.level} onChange={props.setLevel} options={levelOptions} />
            </div>
        </div>
    )
}

function getEditAccessControlRuleModalTitle(scopeType: ScopeType): string {
    switch (scopeType) {
        case 'default':
            return 'Edit default rule'
        case 'role':
            return 'Edit rule for role'
        case 'member':
            return 'Edit rule for member'
    }
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
