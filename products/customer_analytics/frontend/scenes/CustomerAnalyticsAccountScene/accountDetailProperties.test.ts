import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    buildAccountPropertyDescriptors,
    customPropertyProvenance,
    resolvePinnedProperties,
} from './accountDetailProperties'

function buildDefinition(overrides: Partial<CustomPropertyDefinitionApi> = {}): CustomPropertyDefinitionApi {
    return {
        id: 'def-1',
        name: 'Annual recurring revenue',
        display_type: 'currency',
        target_type: 'account',
        is_canonical: false,
        source: null,
        references: [],
        has_workflow_reference: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
    } as CustomPropertyDefinitionApi
}

const OWNER_DEFINITION: AccountRelationshipDefinitionApi = {
    id: 'rel-1',
    name: 'Account owner',
    description: null,
    is_single_holder: true,
}

describe('accountDetailProperties', () => {
    it.each([
        ['a warehouse-backed property', { source: { id: 'src' } }, 'data_warehouse'],
        [
            'a workflow-written property with visible details',
            {
                has_workflow_reference: true,
                references: [{ id: 'wf', name: 'Score', status: 'active', type: 'workflow' }],
            },
            'workflow',
        ],
        ['a workflow-written property with redacted details', { has_workflow_reference: true }, 'workflow'],
        ['a canonical property', { is_canonical: true }, 'auto'],
        ['a plain property', {}, 'manual'],
    ])('derives the provenance of %s', (_label, overrides, expected) => {
        expect(customPropertyProvenance(buildDefinition(overrides as Partial<CustomPropertyDefinitionApi>))).toBe(
            expected
        )
    })

    it('marks workflow-backed properties editable while keeping canonical and warehouse properties read-only', () => {
        const descriptors = buildAccountPropertyDescriptors(
            [
                buildDefinition({ id: 'manual' }),
                buildDefinition({ id: 'workflow', has_workflow_reference: true }),
                buildDefinition({ id: 'canonical', is_canonical: true }),
                buildDefinition({ id: 'synced', source: { id: 'src' } as CustomPropertyDefinitionApi['source'] }),
                buildDefinition({ id: 'person', target_type: 'person' }),
            ],
            [OWNER_DEFINITION, { ...OWNER_DEFINITION, id: 'rel-2', name: 'Champions', is_single_holder: false }]
        )

        expect(descriptors.map((descriptor) => [descriptor.key, descriptor.editable])).toEqual([
            ['custom:manual', true],
            ['custom:workflow', true],
            ['custom:canonical', false],
            ['custom:synced', false],
            ['relationship:rel-1', true],
            ['relationship:rel-2', false],
            ['field:website_domain', false],
            ['field:created_at', false],
            ['field:churned_at', false],
        ])
    })

    it('pins the first custom properties and relationships when nothing is stored, and keeps stored order otherwise', () => {
        const descriptors = buildAccountPropertyDescriptors(
            ['a', 'b', 'c', 'd', 'e'].map((id) => buildDefinition({ id, name: id })),
            [OWNER_DEFINITION]
        )

        expect(resolvePinnedProperties(descriptors, null).map((descriptor) => descriptor.key)).toEqual([
            'custom:a',
            'custom:b',
            'custom:c',
            'custom:d',
        ])
        expect(
            resolvePinnedProperties(descriptors, ['relationship:rel-1', 'custom:gone', 'custom:e']).map(
                (descriptor) => descriptor.key
            )
        ).toEqual(['relationship:rel-1', 'custom:e'])
    })
})
