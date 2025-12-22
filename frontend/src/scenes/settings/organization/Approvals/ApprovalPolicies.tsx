import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonButton, LemonInputSelect, LemonSelect, LemonSwitch, LemonTable, Tooltip } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { APPROVAL_ACTIONS, getApprovalActionLabel } from 'scenes/approvals/utils'
import { membersLogic } from 'scenes/organization/membersLogic'
import { rolesLogic } from 'scenes/settings/organization/Permissions/Roles/rolesLogic'

import { ApprovalPolicy } from '~/types'

import { approvalPoliciesLogic } from './approvalPoliciesLogic'

export function ApprovalPolicies(): JSX.Element {
    const { policies, policiesLoading } = useValues(approvalPoliciesLogic)
    const { loadPolicies, deletePolicy } = useActions(approvalPoliciesLogic)
    const [editingPolicy, setEditingPolicy] = useState<ApprovalPolicy | null>(null)
    const [isCreating, setIsCreating] = useState(false)

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
                <LemonButton type="primary" onClick={() => setIsCreating(true)}>
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

    useEffect(() => {
        loadAllMembers()
        loadRoles()
    }, [loadAllMembers, loadRoles])

    const handleSave = (): void => {
        if (approverUserIds.length === 0 && approverRoleIds.length === 0) {
            lemonToast.error('Please select at least one user or role')
            return
        }

        const policyData = {
            action_key: actionKey,
            approver_config: {
                quorum: quorum,
                users: approverUserIds,
                roles: approverRoleIds,
            },
            allow_self_approve: allowSelfApprove,
            conditions: {},
            bypass_roles: [],
            enabled: true,
        }

        if (policy) {
            updatePolicy(policy.id, policyData)
        } else {
            createPolicy(policyData)
        }
        onClose()
    }

    // Prepare user options for dropdown
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

    // Prepare role options for dropdown
    const roleOptions =
        roles?.map((role) => ({
            key: role.id,
            label: role.name,
        })) || []

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            width={520}
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
                        onChange={setActionKey}
                        options={Object.entries(APPROVAL_ACTIONS).map(([value, action]) => ({
                            label: action.label,
                            value,
                        }))}
                    />
                </div>

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
            </div>
        </LemonModal>
    )
}
