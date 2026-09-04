import { PropertyFilterType, PropertyOperator } from '~/types'

import type {
    AccountTrackRuleGroupApi,
    AccountTrackRuleRunViewApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    accountFiltersToRuleGroup,
    getPreviewRuleColumns,
    getTrackRuleRunDuration,
    getTrackRuleRunTriggerLabel,
    ruleGroupToAccountFilters,
} from './AccountTrackRules'

describe('AccountTrackRules', () => {
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

    it('shows distinct rule properties after the account and external ID columns', () => {
        const groups: AccountTrackRuleGroupApi[] = [
            {
                conditions: [
                    { field: { kind: 'account_field', field: 'name' }, operator: 'exact', values: ['Acme'] },
                    {
                        field: { kind: 'custom_property', definition_id: definition.id },
                        operator: 'gt',
                        values: [100],
                    },
                ],
            },
            {
                conditions: [
                    { field: { kind: 'account_field', field: 'external_id' }, operator: 'is_set', values: [] },
                    {
                        field: { kind: 'custom_property', definition_id: definition.id },
                        operator: 'is_set',
                        values: [],
                    },
                    {
                        field: { kind: 'account_field', field: 'stripe_customer_id' },
                        operator: 'is_set',
                        values: [],
                    },
                ],
            },
        ]

        expect(getPreviewRuleColumns(groups, { [definition.id]: definition })).toEqual([
            { key: `custom_property:${definition.id}`, label: 'MRR', definition },
            { key: 'account_field:stripe_customer_id', label: 'Stripe customer ID' },
        ])
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

    it('labels mixed run triggers and shows duration', () => {
        const scheduledRun = {
            trigger: 'scheduled',
            started_at: '2026-08-20T06:00:00Z',
            finished_at: '2026-08-20T06:01:30Z',
        } as AccountTrackRuleRunViewApi
        const manualRun = {
            trigger: 'manual',
            started_at: null,
            finished_at: null,
        } as AccountTrackRuleRunViewApi

        expect(getTrackRuleRunTriggerLabel(scheduledRun.trigger)).toBe('Scheduled')
        expect(getTrackRuleRunTriggerLabel(manualRun.trigger)).toBe('Manual')
        expect(getTrackRuleRunDuration(scheduledRun)).toBe('1m 30s')
        expect(getTrackRuleRunDuration(manualRun)).toBe('Not started')
    })
})
