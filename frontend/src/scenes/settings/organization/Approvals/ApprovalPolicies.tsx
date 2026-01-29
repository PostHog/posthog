import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconInfo, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonInputSelect,
    LemonSelect,
    LemonSwitch,
    LemonTable,
    Tooltip,
} from '@posthog/lemon-ui'

import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { APPROVAL_ACTIONS, ApprovalActionKey, getApprovalActionLabel } from 'scenes/approvals/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ApprovalPolicy } from '~/types'

import { approvalPoliciesLogic } from './approvalPoliciesLogic'

// Available fields that can be gated
const GATEABLE_FIELDS: Record<string, { label: string; type: 'number' | 'boolean' | 'string' }> = {
    rollout_percentage: { label: 'Rollout percentage', type: 'number' },
}

const CONDITION_TYPES = [
    { value: 'any_change', label: 'changes' },
    { value: 'before_after', label: 'new value is' },
    { value: 'change_amount', label: 'changes by' },
]

const CONDITION_TYPES_TOOLTIP = `• changes – require approval whenever this field is modified
• new value is – require approval when the new value meets a threshold (e.g., rollout > 50%)
• changes by – require approval when the change amount meets a threshold (e.g., increased by more than 10%)`

const OPERATORS = [
    { value: '>', label: '>' },
    { value: '>=', label: '>=' },
    { value: '<', label: '<' },
    { value: '<=', label: '<=' },
    { value: '==', label: '=' },
    { value: '!=', label: '≠' },
]

interface ConditionRule {
    field: string
    type: string
    operator?: string
    value?: number
}

export function ApprovalPolicies(): JSX.Element {
    const { policies, policiesLoading } = useValues(approvalPoliciesLogic)
    const { loadPolicies, deletePolicy } = useActions(approvalPoliciesLogic)
    const [editingPolicy, setEditingPolicy] = useState<ApprovalPolicy | null>(null)
    const [isCreating, setIsCreating] = useState(false)
    const restrictionReason = useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    useEffect(() => {
        loadPolicies()
    }, [loadPolicies])

    const columns: LemonTableColumn<ApprovalPolicy, keyof ApprovalPolicy | undefined>[] = [
        {
            title: 'Action',
            dataIndex: 'action_key',
            render: (_, policy) => getApprovalActionLabel(policy.action_key),
        },
        {
            title: 'Approvers',
            render: (_, policy) => {
                const users = policy.approver_config?.users || []
                const roles = policy.approver_config?.roles || []
                const parts = []
                if (users.length > 0) {
                    parts.push(`${users.length} user${users.length > 1 ? 's' : ''}`)
                }
                if (roles.length > 0) {
                    parts.push(`${roles.length} role${roles.length > 1 ? 's' : ''}`)
                }
                return parts.join(', ') || 'None'
            },
        },
        {
            title: 'Approvals required',
            render: (_, policy) => policy.approver_config?.quorum || 1,
        },
        {
            title: 'Self-approve',
            dataIndex: 'allow_self_approve',
            render: (_, policy) => (policy.allow_self_approve ? 'Yes' : 'No'),
        },
        {
            title: 'Status',
            dataIndex: 'enabled',
            render: (_, policy) => (policy.enabled ? 'Enabled' : 'Disabled'),
        },
        {
            width: 0,
            render: (_, policy) => (
                <More
                    overlay={
                        <>
                            <LemonButton
                                fullWidth
                                onClick={() => {
                                    setEditingPolicy(policy)
                                }}
                                disabledReason={restrictionReason}
                            >
                                Edit
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                status="danger"
                                onClick={() => {
                                    LemonDialog.open({
                                        title: 'Delete approval policy?',
                                        content:
                                            'This will immediately remove the approval requirement for this action.',
                                        primaryButton: {
                                            children: 'Delete',
                                            type: 'primary',
                                            status: 'danger',
                                            onClick: () => deletePolicy(policy.id),
                                            size: 'small',
                                        },
                                        secondaryButton: {
                                            children: 'Cancel',
                                            type: 'tertiary',
                                            size: 'small',
                                        },
                                    })
                                }}
                                disabledReason={restrictionReason}
                            >
                                Delete
                            </LemonButton>
                        </>
                    }
                />
            ),
        },
    ]

    return (
        <div className="space-y-4">
            <div className="flex justify-end items-center">
                <LemonButton type="primary" onClick={() => setIsCreating(true)} disabledReason={restrictionReason}>
                    Add policy
                </LemonButton>
            </div>

            <LemonTable
                dataSource={policies}
                columns={columns}
                loading={policiesLoading}
                rowKey="id"
                nouns={['policy', 'policies']}
                emptyState="No approval policies configured"
            />

            {isCreating && <ApprovalPolicyModal onClose={() => setIsCreating(false)} />}
            {editingPolicy && <ApprovalPolicyModal policy={editingPolicy} onClose={() => setEditingPolicy(null)} />}
        </div>
    )
}

function ApprovalPolicyModal({ policy, onClose }: { policy?: ApprovalPolicy; onClose: () => void }): JSX.Element {
    const { createPolicy, updatePolicy } = useActions(approvalPoliciesLogic)
    const { members } = useValues(membersLogic)
    const { roles } = useValues(rolesLogic)
    const { loadAllMembers } = useActions(membersLogic)
    const { loadRoles } = useActions(rolesLogic)

    const [actionKey, setActionKey] = useState(policy?.action_key || 'feature_flag.enable')
    const [quorum, setQuorum] = useState(policy?.approver_config?.quorum || 1)
    const [allowSelfApprove, setAllowSelfApprove] = useState(policy?.allow_self_approve || false)
    const [approverUserIds, setApproverUserIds] = useState<number[]>(policy?.approver_config?.users || [])
    const [approverRoleIds, setApproverRoleIds] = useState<string[]>(policy?.approver_config?.roles || [])
    const [bypassAdminsOwners, setBypassAdminsOwners] = useState(
        (policy?.bypass_org_membership_levels?.length ?? 0) > 0
    )
    const [bypassRoleIds, setBypassRoleIds] = useState<string[]>(policy?.bypass_roles || [])

    // Parse existing conditions into rules
    const parseExistingConditions = (): ConditionRule[] => {
        const conditions = policy?.conditions as ConditionRule | undefined
        if (conditions?.field) {
            return [
                {
                    field: conditions.field,
                    type: conditions.type || 'any_change',
                    operator: conditions.operator,
                    value: conditions.value,
                },
            ]
        }
        return []
    }

    const [rules, setRules] = useState<ConditionRule[]>(parseExistingConditions())

    useEffect(() => {
        loadAllMembers()
        loadRoles()
    }, [loadAllMembers, loadRoles])

    const addRule = (field: string): void => {
        setRules([...rules, { field, type: 'any_change' }])
    }

    const updateRule = (index: number, updates: Partial<ConditionRule>): void => {
        const newRules = [...rules]
        newRules[index] = { ...newRules[index], ...updates }
        setRules(newRules)
    }

    const removeRule = (index: number): void => {
        setRules(rules.filter((_, i) => i !== index))
    }

    const usedFields = new Set(rules.map((r) => r.field))
    const availableFields = Object.entries(GATEABLE_FIELDS).filter(([key]) => !usedFields.has(key))

    const handleSave = (): void => {
        if (approverUserIds.length === 0 && approverRoleIds.length === 0) {
            lemonToast.error('Please select at least one user or role')
            return
        }

        // Build conditions from rules (for now, just take the first rule)
        let conditions: Record<string, unknown> = {}
        if (actionKey === ApprovalActionKey.FEATURE_FLAG_UPDATE && rules.length > 0) {
            const rule = rules[0]
            if (rule.type !== 'any_change' && rule.value === undefined) {
                lemonToast.error('Please specify a threshold value')
                return
            }
            conditions = {
                type: rule.type,
                field: rule.field,
            }
            if (rule.type !== 'any_change') {
                conditions.operator = rule.operator
                conditions.value = rule.value
            }
        }

        const policyData = {
            action_key: actionKey,
            approver_config: {
                quorum: quorum,
                users: approverUserIds,
                roles: approverRoleIds,
            },
            allow_self_approve: allowSelfApprove,
            conditions,
            bypass_org_membership_levels: bypassAdminsOwners ? ['8', '15'] : [],
            bypass_roles: bypassRoleIds,
            enabled: true,
        }

        if (policy) {
            updatePolicy(policy.id, policyData)
        } else {
            createPolicy(policyData)
        }
        onClose()
    }

    const userOptions =
        members?.map((member) => ({
            key: member.user.id.toString(),
            label: `${member.user.first_name} (${member.user.email})`,
            labelComponent: (
                <div className="flex items-center gap-2">
                    <span>{member.user.first_name}</span>
                    <span className="text-muted text-xs">({member.user.email})</span>
                </div>
            ),
        })) || []

    const roleOptions =
        roles?.map((role) => ({
            key: role.id,
            label: role.name,
        })) || []

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            width={600}
            title={policy ? 'Edit approval policy' : 'Create approval policy'}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleSave}>
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium mb-1">Action type</label>
                    <LemonSelect
                        fullWidth
                        value={actionKey}
                        onChange={(value) => {
                            setActionKey(value)
                            if (value !== ApprovalActionKey.FEATURE_FLAG_UPDATE) {
                                setRules([])
                            }
                        }}
                        options={Object.entries(APPROVAL_ACTIONS).map(([value, action]) => ({
                            label: action.label,
                            value,
                        }))}
                    />
                </div>

                {actionKey === ApprovalActionKey.FEATURE_FLAG_UPDATE && (
                    <div className="space-y-3">
                        <div className="flex items-center gap-2">
                            <label className="block text-sm font-medium">Require approval when</label>
                            <Tooltip title={CONDITION_TYPES_TOOLTIP}>
                                <IconInfo className="text-muted-alt w-4 h-4" />
                            </Tooltip>
                        </div>

                        {rules.length === 0 ? (
                            <div className="p-4 border border-dashed rounded text-center text-muted">
                                No conditions configured. Add a field to require approval for specific changes.
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {rules.map((rule, index) => (
                                    <RuleRow
                                        key={rule.field}
                                        rule={rule}
                                        onChange={(updates) => updateRule(index, updates)}
                                        onRemove={() => removeRule(index)}
                                    />
                                ))}
                            </div>
                        )}

                        {availableFields.length > 0 && (
                            <LemonSelect
                                placeholder="+ Add field"
                                value={null}
                                onChange={(value) => value && addRule(value)}
                                options={availableFields.map(([key, config]) => ({
                                    value: key,
                                    label: config.label,
                                }))}
                                size="small"
                            />
                        )}

                        <p className="text-xs text-secondary">
                            If no conditions are set, all changes to this action type will require approval.
                        </p>
                    </div>
                )}

                <div>
                    <label className="block text-sm font-medium mb-1">Approver users</label>
                    <LemonInputSelect
                        mode="multiple"
                        value={approverUserIds.map(String)}
                        onChange={(values) => setApproverUserIds(values.map(Number))}
                        options={userOptions}
                        placeholder="Select users who can approve"
                    />
                    <p className="text-xs text-secondary mt-1">Users who can approve change requests for this action</p>
                </div>

                <div>
                    <label className="block text-sm font-medium mb-1">Approver roles</label>
                    <LemonInputSelect
                        mode="multiple"
                        value={approverRoleIds}
                        onChange={setApproverRoleIds}
                        options={roleOptions}
                        placeholder="Select roles who can approve"
                    />
                    <p className="text-xs text-secondary mt-1">
                        Users with any of these roles can approve change requests for this action
                    </p>
                </div>

                <div>
                    <label className="block text-sm font-medium mb-1">Approvals required</label>
                    <LemonSelect
                        fullWidth
                        value={quorum}
                        onChange={setQuorum}
                        options={[
                            { label: '1 approval', value: 1 },
                            { label: '2 approvals', value: 2 },
                            { label: '3 approvals', value: 3 },
                        ]}
                    />
                </div>

                <div>
                    <LemonSwitch
                        checked={allowSelfApprove}
                        onChange={setAllowSelfApprove}
                        label={
                            <div className="flex items-center gap-2">
                                <span>Allow self-approval</span>
                                <Tooltip title="If enabled, the person requesting the change can also approve it. They still need to be in the approver list.">
                                    <IconInfo className="text-muted-alt w-4 h-4" />
                                </Tooltip>
                            </div>
                        }
                    />
                </div>

                <div className="border-t pt-4 mt-4">
                    <label className="block text-sm font-medium mb-2">Bypass options</label>
                    <p className="text-xs text-secondary mb-3">
                        Users matching these criteria can skip the approval flow entirely
                    </p>

                    <div className="space-y-3">
                        <LemonSwitch
                            checked={bypassAdminsOwners}
                            onChange={setBypassAdminsOwners}
                            label={
                                <div className="flex items-center gap-2">
                                    <span>Allow org admins and owners to bypass</span>
                                    <Tooltip title="Organization admins and owners can perform this action without requiring approval">
                                        <IconInfo className="text-muted-alt w-4 h-4" />
                                    </Tooltip>
                                </div>
                            }
                        />

                        <div>
                            <label className="block text-sm font-medium mb-1">Bypass roles</label>
                            <LemonInputSelect
                                mode="multiple"
                                value={bypassRoleIds}
                                onChange={setBypassRoleIds}
                                options={roleOptions}
                                placeholder="Select roles that can bypass approval"
                            />
                            <p className="text-xs text-secondary mt-1">
                                Users with any of these roles can skip the approval flow
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}

function RuleRow({
    rule,
    onChange,
    onRemove,
}: {
    rule: ConditionRule
    onChange: (updates: Partial<ConditionRule>) => void
    onRemove: () => void
}): JSX.Element {
    const fieldConfig = GATEABLE_FIELDS[rule.field]
    const isNumeric = fieldConfig?.type === 'number'

    return (
        <div className="flex items-center gap-2 p-2 bg-bg-light border rounded">
            <span className="font-medium text-sm whitespace-nowrap">{fieldConfig?.label || rule.field}</span>

            <LemonSelect
                size="small"
                value={rule.type}
                onChange={(value) => onChange({ type: value })}
                options={CONDITION_TYPES}
            />

            {rule.type !== 'any_change' && isNumeric && (
                <>
                    <LemonSelect
                        size="small"
                        value={rule.operator || '>'}
                        onChange={(value) => onChange({ operator: value })}
                        options={OPERATORS}
                    />
                    <LemonInput
                        size="small"
                        type="number"
                        min={rule.type === 'change_amount' ? -100 : 0}
                        max={100}
                        value={rule.value}
                        onChange={(val) => onChange({ value: val })}
                        placeholder="%"
                        className="w-20"
                    />
                    <span className="text-sm text-muted">%</span>
                </>
            )}

            <div className="flex-1" />

            <LemonButton size="small" icon={<IconX />} onClick={onRemove} tooltip="Remove rule" />
        </div>
    )
}
