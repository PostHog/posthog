import { IconBolt, IconDatabase, IconLogomark, IconPencil } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { AccountCustomPropertyEditor } from './AccountCustomPropertyEditor'
import {
    AccountCustomProperty,
    AccountCustomPropertyValue,
    AccountRelationshipMember,
    AccountRelationshipProperty,
    AccountSidebarProperty,
    isCustomPropertyEditable,
} from './accountPropertyTypes'
import { AccountPropertyValue } from './AccountPropertyValue'
import { AccountRelationshipEditor } from './AccountRelationshipEditor'

const PROVENANCE = {
    workflow: { icon: <IconBolt />, title: 'Updated by a workflow' },
    warehouse: { icon: <IconDatabase />, title: 'Synced from the data warehouse' },
    canonical: { icon: <IconLogomark />, title: 'Managed by PostHog' },
} as const

export interface AccountPropertyRowProps {
    property: AccountSidebarProperty
    editing?: boolean
    saving?: boolean
    availableMembers?: AccountRelationshipMember[]
    membersLoading?: boolean
    onEdit: () => void
    onCancel: () => void
    onSaveCustomProperty: (property: AccountCustomProperty, value: AccountCustomPropertyValue) => void
    onSaveRelationship: (property: AccountRelationshipProperty, memberIds: number[]) => void
}

export function AccountPropertyRow({
    property,
    editing = false,
    saving = false,
    availableMembers = [],
    membersLoading = false,
    onEdit,
    onCancel,
    onSaveCustomProperty,
    onSaveRelationship,
}: AccountPropertyRowProps): JSX.Element {
    const editable =
        property.editable !== false &&
        (property.kind === 'relationship' || isCustomPropertyEditable(property.provenance))
    const provenance =
        property.kind === 'custom' && property.provenance !== 'manual' ? PROVENANCE[property.provenance] : null

    return (
        <div className="flex flex-col gap-1 min-w-0" data-attr="account-property-row">
            <div className="flex items-center gap-1 min-w-0">
                <span className="text-xs text-secondary truncate">{property.definition.name}</span>
                {provenance ? (
                    <Tooltip title={provenance.title}>
                        <span className="flex items-center text-secondary text-xs">{provenance.icon}</span>
                    </Tooltip>
                ) : null}
                {editable && !editing ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconPencil />}
                        tooltip="Edit value"
                        aria-label={`Edit ${property.definition.name}`}
                        onClick={onEdit}
                        className="ml-auto"
                        data-attr="account-property-edit"
                    />
                ) : null}
            </div>
            {editing && editable ? (
                <div className="flex flex-col gap-1.5">
                    {property.kind === 'custom' ? (
                        <AccountCustomPropertyEditor
                            key={property.key}
                            definition={property.definition}
                            value={property.value}
                            saving={saving}
                            onSave={(value) => onSaveCustomProperty(property, value)}
                            onCancel={onCancel}
                        />
                    ) : (
                        <AccountRelationshipEditor
                            key={property.key}
                            definition={property.definition}
                            members={property.members}
                            availableMembers={availableMembers}
                            membersLoading={membersLoading}
                            saving={saving}
                            onSave={(memberIds) => onSaveRelationship(property, memberIds)}
                            onCancel={onCancel}
                        />
                    )}
                    {property.kind === 'custom' && property.provenance === 'workflow' ? (
                        <span className="text-xs text-secondary">A workflow may overwrite this value.</span>
                    ) : null}
                </div>
            ) : (
                <AccountPropertyValue property={property} />
            )}
        </div>
    )
}
