import clsx from 'clsx'

import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { IconGear, IconPin } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { AccountPropertyField, AccountPropertyFieldProps } from './AccountPropertyField'
import type { AccountSidebarProperty } from './accountPropertyTypes'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

export interface AccountPinnedPropertiesProps {
    properties: AccountSidebarProperty[]
    layout?: 'vertical' | 'horizontal'
    editingPropertyKey?: string | null
    savingPropertyKey?: string | null
    availableMembers?: AccountPropertyFieldProps['availableMembers']
    membersLoading?: boolean
    onConfigure: () => void
    onEdit: (property: AccountSidebarProperty) => void
    onCancelEdit: () => void
    onSaveCustomProperty: AccountPropertyFieldProps['onSaveCustomProperty']
    onSaveRelationship: AccountPropertyFieldProps['onSaveRelationship']
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
    layout = 'vertical',
    editingPropertyKey = null,
    savingPropertyKey = null,
    availableMembers,
    membersLoading,
    onConfigure,
    onEdit,
    onCancelEdit,
    onSaveCustomProperty,
    onSaveRelationship,
}: AccountPinnedPropertiesProps): JSX.Element {
    return (
        <section className="flex flex-col flex-1 min-h-0 overflow-hidden" data-attr="account-pinned-properties">
            <div className="flex items-center shrink-0 px-4 pt-4">
                <span className="secondary text-secondary">Properties</span>
                {properties.length > 0 ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconGear />}
                        className={layout === 'horizontal' ? 'ml-1' : 'ml-auto'}
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
                <div
                    className={clsx(
                        'flex gap-4 min-h-0 overflow-y-auto px-4 pt-4 pb-5',
                        layout === 'horizontal' ? 'flex-wrap items-start' : 'flex-col'
                    )}
                >
                    {properties.map((property) => (
                        <div
                            key={property.key}
                            className={clsx(
                                'min-w-0',
                                layout === 'horizontal' && 'max-w-64',
                                layout === 'horizontal' && editingPropertyKey === property.key && 'w-64'
                            )}
                        >
                            <AccountPropertyField
                                property={property}
                                editing={editingPropertyKey === property.key}
                                saving={savingPropertyKey === property.key}
                                availableMembers={availableMembers}
                                membersLoading={membersLoading}
                                onEdit={() => onEdit(property)}
                                onCancel={onCancelEdit}
                                onSaveCustomProperty={onSaveCustomProperty}
                                onSaveRelationship={onSaveRelationship}
                            />
                        </div>
                    ))}
                </div>
            )}
        </section>
    )
}
