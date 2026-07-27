import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'

import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    buildAccountColumnGroups,
    customPropertyAlias,
    relationshipAlias,
    roleKeyToDefinitionMap,
    translateSelectColumns,
} from './accountsColumnConfigLogic'

function definition(
    id: string,
    name: string,
    overrides: Partial<CustomPropertyDefinitionApi> = {}
): CustomPropertyDefinitionApi {
    return {
        id,
        name,
        display_type: 'text',
        is_big_number: false,
        description: null,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
        updated_at: null,
        references: [],
        source: null,
        ...overrides,
    }
}

const relationshipDefinition = (
    id: string,
    name: string,
    overrides: Partial<AccountRelationshipDefinitionApi> = {}
): AccountRelationshipDefinitionApi => ({
    id,
    name,
    description: null,
    is_single_holder: true,
    ...overrides,
})

describe('accountsColumnConfigLogic column groups and translation', () => {
    it('emits a custom_properties group with one option per definition, right after account_properties', () => {
        const defs = [
            definition('11111111-2222-3333-4444-555555555555', 'Plan', { display_type: 'currency' }),
            definition('66666666-7777-8888-9999-000000000000', 'Renewal', { display_type: 'date' }),
        ]
        const groups = buildAccountColumnGroups({}, [], defs)

        const keys = groups.map((group) => group.key)
        expect(keys[0]).toBe('account_properties')
        expect(keys[1]).toBe('custom_properties')

        const group = groups.find((g) => g.key === 'custom_properties')!
        expect(group.label).toBe('Custom properties')
        expect(group.options).toEqual([
            {
                name: 'Plan',
                type: 'currency',
                expression: `accounts.custom_properties.values.\`11111111-2222-3333-4444-555555555555\` AS ${customPropertyAlias(
                    '11111111-2222-3333-4444-555555555555'
                )}`,
            },
            {
                name: 'Renewal',
                type: 'date',
                expression: `accounts.custom_properties.values.\`66666666-7777-8888-9999-000000000000\` AS ${customPropertyAlias(
                    '66666666-7777-8888-9999-000000000000'
                )}`,
            },
        ])
    })

    it('omits the group entirely when the team has no definitions', () => {
        const groups = buildAccountColumnGroups({}, [], [])
        expect(groups.map((group) => group.key)).not.toContain('custom_properties')
    })

    it('round-trips the alias: extractDisplayLabel of the expression yields the column alias', () => {
        const id = 'abcdabcd-1234-5678-9abc-def012345678'
        const group = buildAccountColumnGroups({}, [], [definition(id, 'Plan')]).find(
            (g) => g.key === 'custom_properties'
        )!
        expect(extractDisplayLabel(group.options[0].expression)).toBe(customPropertyAlias(id))
    })

    it('relationships group offers legacy names for seeded definitions and rel_ aliases for others', () => {
        const seeded = relationshipDefinition('11111111-2222-3333-4444-555555555555', 'CSM')
        const custom = relationshipDefinition('66666666-7777-8888-9999-000000000000', 'Onboarding manager')
        const group = buildAccountColumnGroups({}, [], [], [seeded, custom]).find((g) => g.key === 'relationships')!

        expect(group.options).toEqual([
            { name: 'CSM', expression: 'csm' },
            {
                name: 'Onboarding manager',
                expression: `accounts.relationships.values.\`${custom.id}\` AS ${relationshipAlias(custom.id)}`,
            },
        ])
    })

    it('omits the relationships group when the team has no definitions', () => {
        expect(buildAccountColumnGroups({}, [], [], []).map((group) => group.key)).not.toContain('relationships')
    })

    it('translateSelectColumns resolves legacy roles through the lazy join and drops unmatched ones', () => {
        const csm = relationshipDefinition('11111111-2222-3333-4444-555555555555', 'CSM')
        const map = roleKeyToDefinitionMap([
            csm,
            relationshipDefinition('99999999-0000-1111-2222-333333333333', 'Renamed'),
        ])

        expect(translateSelectColumns(['name', 'csm', 'account_owner'], map)).toEqual([
            'name',
            `accounts.relationships.values.\`${csm.id}\` AS csm`,
        ])
    })
})
