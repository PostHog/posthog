import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
    CustomPropertyDisplayTypeEnumApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { AccountPinnedProperties } from './AccountPinnedProperties'
import { AccountPropertyConfigurator } from './AccountPropertyConfigurator'
import { AccountPropertyRow } from './AccountPropertyRow'
import type {
    AccountCustomProperty,
    AccountCustomPropertyValue,
    AccountPropertyOption,
    AccountRelationshipMember,
    AccountRelationshipProperty,
    AccountSidebarProperty,
} from './accountPropertyTypes'

const MEMBERS: AccountRelationshipMember[] = [
    { id: 1, name: 'Riley Chen', email: 'riley@example.com' },
    { id: 2, name: 'Jordan Bell', email: 'jordan@example.com' },
    { id: 3, name: 'Sam Rivera', email: 'sam@example.com' },
]

function customDefinition(
    id: string,
    name: string,
    displayType: CustomPropertyDisplayTypeEnumApi,
    overrides: Partial<CustomPropertyDefinitionApi> = {}
): CustomPropertyDefinitionApi {
    return {
        id,
        name,
        description: null,
        display_type: displayType,
        target_type: 'account',
        group_type_index: null,
        is_big_number: false,
        is_canonical: false,
        options: null,
        source: null,
        created_at: '2026-08-01T12:00:00Z',
        created_by: 1,
        updated_at: null,
        references: [],
        has_workflow_reference: false,
        ...overrides,
    }
}

function customProperty(
    id: string,
    name: string,
    displayType: CustomPropertyDisplayTypeEnumApi,
    value: AccountCustomPropertyValue,
    overrides: Partial<AccountCustomProperty> = {}
): AccountCustomProperty {
    return {
        key: `custom:${id}`,
        kind: 'custom',
        definition: customDefinition(id, name, displayType),
        value,
        provenance: 'manual',
        ...overrides,
    }
}

function relationshipProperty(
    id: string,
    name: string,
    members: AccountRelationshipMember[],
    isSingleHolder: boolean
): AccountRelationshipProperty {
    const definition: AccountRelationshipDefinitionApi = {
        id,
        name,
        description: null,
        is_single_holder: isSingleHolder,
    }
    return { key: `relationship:${id}`, kind: 'relationship', definition, members }
}

const DISPLAY_PROPERTIES: AccountSidebarProperty[] = [
    customProperty('arr', 'Annual recurring revenue', 'currency', 125000),
    customProperty('growth', 'Monthly growth', 'percent', 0.184),
    customProperty('plan', 'Plan', 'select', 'Enterprise', {
        definition: customDefinition('plan', 'Plan', 'select', {
            options: [{ id: 'enterprise', label: 'Enterprise', color: 'preset-5' }],
        }),
    }),
    customProperty('renewal', 'Renewal date', 'date', '2026-11-14'),
    customProperty('health', 'Healthy', 'boolean', true, {
        provenance: 'workflow',
        definition: customDefinition('health', 'Healthy', 'boolean', { has_workflow_reference: true }),
    }),
    customProperty('warehouse', 'Warehouse tier', 'text', 'Gold', { provenance: 'warehouse' }),
    customProperty('canonical', 'First seen', 'datetime', '2026-08-20T15:30:00Z', {
        provenance: 'canonical',
        definition: customDefinition('canonical', 'First seen', 'datetime', { is_canonical: true }),
    }),
    relationshipProperty('csm', 'Customer success manager', [MEMBERS[0]], true),
]

const noop = (): void => {}

const meta: Meta = {
    title: 'Scenes-App/Customer Analytics/Account detail/Property sidebar',
    component: AccountPinnedProperties,
    parameters: {
        layout: 'centered',
        mockDate: '2026-09-04T12:00:00Z',
        testOptions: { viewport: { width: 420, height: 800 } },
    },
    decorators: [
        (Story) => (
            <div className="w-96 h-176 border rounded flex flex-col min-h-0 bg-surface-primary">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj

export const Empty: Story = {
    render: () => (
        <AccountPinnedProperties
            properties={[]}
            onConfigure={noop}
            onEdit={noop}
            onCancelEdit={noop}
            onSaveCustomProperty={noop}
            onSaveRelationship={noop}
        />
    ),
}

export const FilledAndScrollable: Story = {
    render: () => (
        <AccountPinnedProperties
            properties={[
                ...DISPLAY_PROPERTIES,
                ...DISPLAY_PROPERTIES.map((property) => ({ ...property, key: `${property.key}:2` })),
            ]}
            availableMembers={MEMBERS}
            onConfigure={noop}
            onEdit={noop}
            onCancelEdit={noop}
            onSaveCustomProperty={noop}
            onSaveRelationship={noop}
        />
    ),
}

export const CustomPropertyEditors: Story = {
    render: () => (
        <div className="flex flex-col gap-5 p-4 overflow-y-auto">
            {[
                customProperty('text', 'Account summary', 'text', 'Rolling out to the product team'),
                customProperty('link', 'Success plan', 'link', 'https://example.com/success-plan'),
                customProperty('amount', 'Expansion potential', 'currency', 45000),
                customProperty('active', 'Active', 'boolean', true),
                customProperty('segment', 'Segment', 'select', 'Mid-market', {
                    definition: customDefinition('segment', 'Segment', 'select', {
                        options: [
                            { id: 'smb', label: 'SMB', color: 'preset-1' },
                            { id: 'mid', label: 'Mid-market', color: 'preset-3' },
                            { id: 'ent', label: 'Enterprise', color: 'preset-5' },
                        ],
                    }),
                }),
            ].map((property) => (
                <AccountPropertyRow
                    key={property.key}
                    property={property}
                    editing
                    onEdit={noop}
                    onCancel={noop}
                    onSaveCustomProperty={noop}
                    onSaveRelationship={noop}
                />
            ))}
        </div>
    ),
}

export const DateAndDatetimeEditors: Story = {
    render: () => (
        <div className="flex flex-col gap-5 p-4">
            {[
                customProperty('date', 'Renewal date', 'date', '2026-11-14'),
                customProperty('datetime', 'Next check-in', 'datetime', '2026-09-18T14:30:00Z'),
            ].map((property) => (
                <AccountPropertyRow
                    key={property.key}
                    property={property}
                    editing
                    onEdit={noop}
                    onCancel={noop}
                    onSaveCustomProperty={noop}
                    onSaveRelationship={noop}
                />
            ))}
        </div>
    ),
}

export const RelationshipEditors: Story = {
    render: () => (
        <div className="flex flex-col gap-5 p-4">
            {[
                relationshipProperty('owner', 'Account owner', [MEMBERS[0]], true),
                relationshipProperty('team', 'Account team', [MEMBERS[0], MEMBERS[1]], false),
            ].map((property) => (
                <AccountPropertyRow
                    key={property.key}
                    property={property}
                    editing
                    availableMembers={MEMBERS}
                    onEdit={noop}
                    onCancel={noop}
                    onSaveCustomProperty={noop}
                    onSaveRelationship={noop}
                />
            ))}
        </div>
    ),
}

const CONFIG_OPTIONS: AccountPropertyOption[] = DISPLAY_PROPERTIES.map((property) => ({
    key: property.key,
    label: property.definition.name,
    kind: property.kind,
}))

export const PinAndReorder: Story = {
    render: function Render() {
        const [pinnedPropertyKeys, setPinnedPropertyKeys] = useState(CONFIG_OPTIONS.slice(0, 3).map(({ key }) => key))
        return (
            <AccountPropertyConfigurator
                isOpen
                options={CONFIG_OPTIONS}
                pinnedPropertyKeys={pinnedPropertyKeys}
                onChange={setPinnedPropertyKeys}
                onSave={noop}
                onCancel={noop}
            />
        )
    },
}

const LIMIT_OPTIONS: AccountPropertyOption[] = Array.from({ length: 51 }, (_, index) => ({
    key: `custom:limit-${index}`,
    label: `Property ${index + 1}`,
    kind: 'custom',
}))

export const PinLimitReached: Story = {
    render: () => (
        <AccountPropertyConfigurator
            isOpen
            options={LIMIT_OPTIONS}
            pinnedPropertyKeys={LIMIT_OPTIONS.slice(0, 50).map(({ key }) => key)}
            onChange={noop}
            onSave={noop}
            onCancel={noop}
        />
    ),
}
