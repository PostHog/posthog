import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { filterTestAccountsDefaultsLogic } from './filterTestAccountDefaultsLogic'

describe('filterTestAccountsDefaultsLogic default filters', () => {
    const filters: AnyPropertyFilter[] = [
        {
            key: 'email',
            type: PropertyFilterType.Person,
            operator: PropertyOperator.NotIContains,
            value: '@example.com',
        },
    ]

    it.each([
        ['the team turned it on', { filters, apply_to_new_insights: true }, true],
        ['the team has filters but did not turn it on', { filters, apply_to_new_insights: false }, false],
        ['the team turned it on without filters', { filters: [], apply_to_new_insights: true }, true],
        ['the team has no default filters config', undefined, false],
    ])('sets applyDefaultFiltersDefault when %s', (_name, config, expected) => {
        initKeaTests(true, { ...MOCK_DEFAULT_TEAM, default_filters_config: config })
        const logic = filterTestAccountsDefaultsLogic()
        logic.mount()

        expect(logic.values.applyDefaultFiltersDefault).toBe(expected)
    })
})
