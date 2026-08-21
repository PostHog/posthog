import { PropertyFilterType, PropertyOperator } from '~/types'

import type {
    AccountTrackRuleGroupApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { accountFiltersToRuleGroup, ruleGroupToAccountFilters } from './AccountTrackRules'

describe('AccountTrackRules filter translation', () => {
    const definition = {
        id: '01980d7c-0000-7000-8000-000000000001',
        name: 'MRR',
        display_type: 'currency',
    } as CustomPropertyDefinitionApi

    it('round-trips native and custom property conditions without display labels', () => {
        const group: AccountTrackRuleGroupApi = {
            conditions: [
                {
                    field: { kind: 'account_field', field: 'name' },
                    operator: 'icontains',
                    values: ['PostHog'],
                },
                {
                    field: { kind: 'custom_property', definition_id: definition.id },
                    operator: 'gt',
                    values: [100],
                },
            ],
        }

        const filters = ruleGroupToAccountFilters(group, { [definition.id]: definition })

        expect(filters).toEqual([
            {
                key: 'name',
                value: ['PostHog'],
                operator: PropertyOperator.IContains,
                type: PropertyFilterType.Account,
            },
            {
                key: definition.id,
                value: [100],
                operator: PropertyOperator.GreaterThan,
                type: PropertyFilterType.AccountCustomProperty,
                label: 'MRR',
            },
        ])
        expect(accountFiltersToRuleGroup(filters)).toEqual(group)
        expect(JSON.stringify(accountFiltersToRuleGroup(filters))).not.toContain('MRR')
    })

    it('keeps set operators value-free', () => {
        const group = accountFiltersToRuleGroup([
            {
                key: 'external_id',
                operator: PropertyOperator.IsNotSet,
                type: PropertyFilterType.Account,
            },
        ])

        expect(group.conditions).toEqual([
            {
                field: { kind: 'account_field', field: 'external_id' },
                operator: 'is_not_set',
                values: [],
            },
        ])
    })
})
