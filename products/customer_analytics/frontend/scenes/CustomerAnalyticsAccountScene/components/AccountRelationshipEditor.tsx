import { useState } from 'react'

import { LemonButton, LemonDialog, LemonInputSelect } from '@posthog/lemon-ui'

import type { AccountRelationshipDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { AccountRelationshipMember } from './accountPropertyTypes'

export interface AccountRelationshipEditorProps {
    definition: AccountRelationshipDefinitionApi
    members: AccountRelationshipMember[]
    availableMembers: AccountRelationshipMember[]
    membersLoading?: boolean
    saving?: boolean
    onSave: (memberIds: number[]) => void
    onCancel: () => void
}

export function AccountRelationshipEditor({
    definition,
    members,
    availableMembers,
    membersLoading = false,
    saving = false,
    onSave,
    onCancel,
}: AccountRelationshipEditorProps): JSX.Element {
    const [draftMemberIds, setDraftMemberIds] = useState<number[]>(members.map((member) => member.id))

    const confirmClear = (): void => {
        LemonDialog.open({
            title: `Clear ${definition.name}?`,
            content: 'This clears the assignments you were editing. New assignments added elsewhere will be kept.',
            primaryButton: {
                children: 'Clear value',
                status: 'danger',
                onClick: () => onSave([]),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    return (
        <div className="flex flex-col gap-2 w-full">
            <LemonInputSelect<number>
                loading={membersLoading}
                mode={definition.is_single_holder === false ? 'multiple' : 'single'}
                value={draftMemberIds}
                onChange={setDraftMemberIds}
                options={availableMembers.map((member) => ({
                    key: String(member.id),
                    value: member.id,
                    label: member.name ? `${member.name} (${member.email})` : member.email,
                }))}
                placeholder="Select a team member"
                size="small"
                fullWidth
                singleValueAsSnack
                disabledReason={saving ? 'Saving' : undefined}
                data-attr="account-relationship-members-input"
            />
            <div className="flex flex-wrap items-center justify-end gap-1 w-full">
                <LemonButton
                    size="xsmall"
                    status="danger"
                    onClick={confirmClear}
                    disabledReason={
                        saving ? 'Saving' : members.length === 0 ? 'This relationship is unassigned' : undefined
                    }
                    data-attr="account-relationship-clear"
                >
                    Clear value
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    onClick={onCancel}
                    disabledReason={saving ? 'Saving' : undefined}
                    data-attr="account-relationship-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="xsmall"
                    onClick={() => onSave(draftMemberIds)}
                    loading={saving}
                    data-attr="account-relationship-save"
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
