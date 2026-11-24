import clsx from 'clsx'

import * as businessEvolutionPng from '@posthog/brand/hoggies/png/business-evolution'
import { IconGear, IconPin } from '@posthog/icons'
import { LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { Badge, Tooltip as QuillTooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { PinnedAccountPropertiesSourceApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountPropertyField, AccountPropertyFieldProps } from './AccountPropertyField'
import type { AccountSidebarProperty } from './accountPropertyTypes'

const HedgehogBusiness = pngHoggie(businessEvolutionPng)

interface PinnedPropertySourceChip {
    key: string
    label: string
    tooltip: string
}

function getSourceChips(source: PinnedAccountPropertiesSourceApi | null | undefined): PinnedPropertySourceChip[] {
    if (!source || source.kind === 'personal') {
        return []
    }
    if (source.kind === 'project') {
        return [{ key: 'project', label: 'Project default', tooltip: 'Default properties for this project' }]
    }
    return source.roles.map((role) => ({
        key: role.id,
        label: role.name,
        tooltip: `Default properties for the ${role.name} role`,
    }))
}

export interface AccountPinnedPropertiesProps {
    properties: AccountSidebarProperty[]
    pinnedPropertiesSource?: PinnedAccountPropertiesSourceApi | null
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
    pinnedPropertiesSource = null,
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const sourceChips = properties.length > 0 ? getSourceChips(pinnedPropertiesSource) : []

    return (
        <section className="flex flex-col flex-1 min-h-0 overflow-hidden" data-attr="account-pinned-properties">
            <div
                className={clsx(
                    'flex shrink-0 px-4 pt-4',
                    sourceChips.length > 0 ? 'items-start gap-x-2' : 'items-center',
                    layout === 'horizontal' ? 'justify-start' : 'justify-between'
                )}
            >
                <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 min-w-0">
                    <span
                        className={clsx(
                            'secondary text-secondary shrink-0',
                            sourceChips.length > 0 && 'inline-flex items-center min-h-[1.625rem]'
                        )}
                    >
                        Properties
                    </span>
                    {sourceChips.map((chip) =>
                        todayRailNav ? (
                            <QuillTooltip key={chip.key}>
                                <TooltipTrigger
                                    render={
                                        <Badge
                                            variant="default"
                                            className="max-w-full min-w-0 shrink justify-start"
                                            data-attr="account-pinned-properties-source"
                                        />
                                    }
                                >
                                    <span className="truncate min-w-0">{chip.label}</span>
                                </TooltipTrigger>
                                <TooltipContent>{chip.tooltip}</TooltipContent>
                            </QuillTooltip>
                        ) : (
                            <Tooltip key={chip.key} title={chip.tooltip}>
                                <LemonTag
                                    size="small"
                                    type="muted"
                                    className="max-w-full min-w-0"
                                    data-attr="account-pinned-properties-source"
                                >
                                    <span className="truncate min-w-0">{chip.label}</span>
                                </LemonTag>
                            </Tooltip>
                        )
                    )}
                </div>
                {properties.length > 0 ? (
                    <LemonButton
                        size="xsmall"
                        icon={<IconGear />}
                        className={clsx('shrink-0', sourceChips.length === 0 && layout === 'horizontal' && 'ml-1')}
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
