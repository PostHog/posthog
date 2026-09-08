import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { IconGear, IconPin } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { AccountPropertyRow, AccountPropertyRowProps } from './AccountPropertyRow'
import type { AccountSidebarProperty } from './accountPropertyTypes'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

export interface AccountPinnedPropertiesProps {
    properties: AccountSidebarProperty[]
    editingPropertyKey?: string | null
    savingPropertyKey?: string | null
    availableMembers?: AccountPropertyRowProps['availableMembers']
    onConfigure: () => void
    onEdit: (property: AccountSidebarProperty) => void
    onCancelEdit: () => void
    onSaveCustomProperty: AccountPropertyRowProps['onSaveCustomProperty']
    onSaveRelationship: AccountPropertyRowProps['onSaveRelationship']
}

export function AccountPinnedPropertiesEmptyState({ onConfigure }: { onConfigure: () => void }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-3 px-5 py-6 text-center">
            <HedgehogBusiness className="w-16 h-16" />
            <p className="text-sm text-secondary mb-0">Pin the account details you use most.</p>
            <LemonButton
                type="primary"
                size="small"
                icon={<IconPin />}
                onClick={onConfigure}
                data-attr="account-pin-properties-empty"
            >
                Pin properties
            </LemonButton>
        </div>
    )
}

export function AccountPinnedProperties({
    properties,
    editingPropertyKey = null,
    savingPropertyKey = null,
    availableMembers,
    onConfigure,
    onEdit,
    onCancelEdit,
    onSaveCustomProperty,
    onSaveRelationship,
}: AccountPinnedPropertiesProps): JSX.Element {
    return (
        <section className="flex flex-col flex-1 min-h-0 overflow-hidden" data-attr="account-pinned-properties">
            <div className="flex items-center shrink-0 px-5 pt-4">
                <span className="secondary text-secondary">Properties</span>
                {properties.length > 0 ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconGear />}
                        className="ml-auto"
                        tooltip="Choose pinned properties"
                        aria-label="Configure pinned properties"
                        onClick={onConfigure}
                        data-attr="account-configure-pinned-properties"
                    />
                ) : null}
            </div>
            {properties.length === 0 ? (
                <AccountPinnedPropertiesEmptyState onConfigure={onConfigure} />
            ) : (
                <div className="flex flex-col gap-4 min-h-0 overflow-y-auto px-5 pt-4 pb-5">
                    {properties.map((property) => (
                        <AccountPropertyRow
                            key={property.key}
                            property={property}
                            editing={editingPropertyKey === property.key}
                            saving={savingPropertyKey === property.key}
                            availableMembers={availableMembers}
                            onEdit={() => onEdit(property)}
                            onCancel={onCancelEdit}
                            onSaveCustomProperty={onSaveCustomProperty}
                            onSaveRelationship={onSaveRelationship}
                        />
                    ))}
                </div>
            )}
        </section>
    )
}
