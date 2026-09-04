import { useActions, useValues } from 'kea'

import { IconBolt, IconDatabase, IconLogomark, IconPencil } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { MemberSelect } from 'lib/components/MemberSelect'

import type { AccountApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountPropertyDescriptor, AccountPropertyProvenance } from '../accountDetailProperties'
import { accountDetailPropertiesLogic } from '../accountDetailPropertiesLogic'
import { AccountPropertyEditor } from './AccountPropertyEditor'
import { AccountPropertyValue } from './AccountPropertyValue'

const PROVENANCE_GLYPHS: Record<Exclude<AccountPropertyProvenance, 'manual'>, { icon: JSX.Element; title: string }> = {
    data_warehouse: { icon: <IconDatabase />, title: 'Synced from the data warehouse' },
    workflow: { icon: <IconBolt />, title: 'Computed by a workflow' },
    auto: { icon: <IconLogomark />, title: 'Set by PostHog' },
}

interface AccountPropertyRowProps {
    accountId: string
    account: AccountApi
    descriptor: AccountPropertyDescriptor
}

export function AccountPropertyRow({ accountId, account, descriptor }: AccountPropertyRowProps): JSX.Element {
    const logic = accountDetailPropertiesLogic({ accountId })
    const { editingPropertyKey, valueByDefinitionId, userIdsByRelationshipDefinitionId, isPropertySaving } =
        useValues(logic)
    const { setEditingPropertyKey, saveCustomPropertyValue, assignRelationship } = useActions(logic)

    const glyph = descriptor.provenance === 'manual' ? null : PROVENANCE_GLYPHS[descriptor.provenance]
    const customValue = descriptor.kind === 'custom' ? valueByDefinitionId[descriptor.definition.id] : undefined
    const relationshipUserIds =
        descriptor.kind === 'relationship'
            ? (userIdsByRelationshipDefinitionId[descriptor.relationshipDefinition.id] ?? [])
            : []
    const saving = isPropertySaving(descriptor.key)
    const editing = editingPropertyKey === descriptor.key

    let editControl: JSX.Element | null = null
    if (descriptor.kind === 'custom' && descriptor.editable) {
        editControl = (
            <LemonButton
                size="xsmall"
                icon={<IconPencil />}
                tooltip="Edit value"
                aria-label={`Edit ${descriptor.label}`}
                onClick={() => setEditingPropertyKey(editing ? null : descriptor.key)}
                data-attr="account-property-edit"
            />
        )
    } else if (descriptor.kind === 'relationship' && descriptor.editable) {
        editControl = (
            <MemberSelect
                value={relationshipUserIds[0] ?? null}
                defaultLabel="Unassigned"
                onChange={(user) => assignRelationship(descriptor.relationshipDefinition.id, user)}
            >
                {() => (
                    <LemonButton
                        size="xsmall"
                        icon={<IconPencil />}
                        tooltip={`Change ${descriptor.label.toLowerCase()}`}
                        aria-label={`Change ${descriptor.label}`}
                        loading={saving}
                        disabledReason={saving ? 'Saving…' : undefined}
                        data-attr="account-property-assign"
                    />
                )}
            </MemberSelect>
        )
    }

    return (
        <div className="flex flex-col gap-0.5 min-w-0" data-attr="account-property-row">
            <div className="flex items-center gap-1 min-w-0">
                <span className="text-xs text-secondary truncate">{descriptor.label}</span>
                {glyph ? (
                    <Tooltip title={glyph.title}>
                        <span className="flex items-center text-secondary opacity-75 text-xs">{glyph.icon}</span>
                    </Tooltip>
                ) : null}
                <span className="ml-auto flex items-center">{editControl}</span>
            </div>
            {editing && descriptor.kind === 'custom' ? (
                <AccountPropertyEditor
                    definition={descriptor.definition}
                    value={customValue}
                    saving={saving}
                    onSave={(value) => saveCustomPropertyValue(descriptor.definition.id, value)}
                    onCancel={() => setEditingPropertyKey(null)}
                />
            ) : (
                <div className="flex flex-col min-w-0">
                    <AccountPropertyValue
                        descriptor={descriptor}
                        account={account}
                        customValue={customValue}
                        relationshipUserIds={relationshipUserIds}
                    />
                </div>
            )}
        </div>
    )
}
