import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { dashboardFiltersLogic } from './dashboardFiltersLogic'

describe('dashboardFiltersLogic', () => {
    let logic: ReturnType<typeof dashboardFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('filter actions', () => {
        beforeEach(() => {
            logic = dashboardFiltersLogic({ id: 1 })
            logic.mount()
        })

        it('setDates updates effectiveEditBarFilters', () => {
            logic.actions.setDates('-7d', null)

            expect(logic.values.effectiveEditBarFilters).toMatchObject({
                date_from: '-7d',
                date_to: null,
            })
        })

        it('setProperties updates effectiveEditBarFilters', () => {
            logic.actions.setProperties([
                { key: 'browser', value: 'Chrome', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
            ])

            expect(logic.values.effectiveEditBarFilters).toMatchObject({
                properties: [{ key: 'browser', value: 'Chrome', type: 'event', operator: 'exact' }],
            })
        })

        it('resetIntermittentFilters clears intermittent state', () => {
            logic.actions.setDates('-7d', null)
            expect(logic.values.hasIntermittentFilters).toBe(true)

            logic.actions.resetIntermittentFilters()
            expect(logic.values.hasIntermittentFilters).toBe(false)
        })
    })

    describe('memoization', () => {
        beforeEach(() => {
            logic = dashboardFiltersLogic({ id: 1 })
            logic.mount()
        })

        it('effectiveEditBarFilters returns same reference when inputs produce equal output', () => {
            logic.actions.setDates('-7d', undefined)
            const first = logic.values.effectiveEditBarFilters

            logic.actions.resetIntermittentFilters()
            logic.actions.setDates('-7d', undefined)
            const second = logic.values.effectiveEditBarFilters

            expect(first).toBe(second)
        })

        it('effectiveEditBarFilters returns new reference when filters change', () => {
            logic.actions.setDates('-7d', null)
            const first = logic.values.effectiveEditBarFilters

            logic.actions.setDates('-30d', null)
            const second = logic.values.effectiveEditBarFilters

            expect(first).not.toBe(second)
        })
    })

    describe('filter combination precedence', () => {
        it.each([
            {
                name: 'persisted only',
                persisted: { date_from: '-24h' },
                external: {},
                intermittent: {},
                expected: { date_from: '-24h' },
            },
            {
                name: 'external overrides persisted',
                persisted: { date_from: '-24h' },
                external: { date_from: '-7d' },
                intermittent: {},
                expected: { date_from: '-7d' },
            },
            {
                name: 'intermittent overrides external and persisted',
                persisted: { date_from: '-24h' },
                external: { date_from: '-7d' },
                intermittent: { date_from: '-30d' },
                expected: { date_from: '-30d' },
            },
            {
                name: 'undefined intermittent values do not override',
                persisted: { date_from: '-24h' },
                external: {},
                intermittent: { date_from: undefined },
                expected: { date_from: '-24h' },
            },
        ])('$name', ({ persisted, external, intermittent }) => {
            logic = dashboardFiltersLogic({ id: 2 })
            logic.mount()

            logic.actions.setPersistedFilters(persisted)
            logic.actions.setExternalFilters(external)

            if (intermittent.date_from !== undefined) {
                logic.actions.setDates(intermittent.date_from as string, undefined)
            }

            expectLogic(logic).toMatchValues({
                effectiveEditBarFilters: expect.objectContaining({
                    date_from: intermittent.date_from ?? external.date_from ?? persisted.date_from,
                }),
            })
        })
    })

    describe('persisted state sync', () => {
        it('setPersistedFilters updates effectiveEditBarFilters', () => {
            logic = dashboardFiltersLogic({ id: 3 })
            logic.mount()

            logic.actions.setPersistedFilters({ date_from: '-90d' })
            expect(logic.values.effectiveEditBarFilters).toMatchObject({ date_from: '-90d' })
        })

        it('setPersistedVariables updates effectiveDashboardVariableOverrides', () => {
            logic = dashboardFiltersLogic({ id: 4 })
            logic.mount()

            const variables = { var1: { code_name: 'test', variableId: 'var1', value: '42' } }
            logic.actions.setPersistedVariables(variables)
            expect(logic.values.effectiveDashboardVariableOverrides).toEqual(variables)
        })
    })
})
