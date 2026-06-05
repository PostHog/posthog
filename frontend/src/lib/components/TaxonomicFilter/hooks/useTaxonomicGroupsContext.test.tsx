import { cleanup, renderHook } from '@testing-library/react'
import { Provider } from 'kea'
import { ReactNode } from 'react'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { TaxonomicFilterGroupType } from '../types'
import { buildTaxonomicGroups } from '../utils/buildTaxonomicGroups'
import { useTaxonomicGroupsContext } from './useTaxonomicGroupsContext'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

const wrapper = ({ children }: { children: ReactNode }): JSX.Element => <Provider>{children}</Provider>

describe('useTaxonomicGroupsContext', () => {
    beforeEach(() => {
        ;(performQuery as jest.Mock).mockResolvedValue({ tables: {}, joins: [] })
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': { results: [], count: 0 },
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('returns a context with required keys and arrays defaulted', () => {
        const { result } = renderHook(() => useTaxonomicGroupsContext({}), { wrapper })
        const ctx = result.current
        expect(ctx).toMatchObject({
            eventNames: [],
            schemaColumns: [],
            maxContextOptions: [],
            hideBehavioralCohorts: false,
            propertyFilters: { excludedProperties: {} },
            hogQLExpressionComponentProps: { showBreakdownLabelHint: false },
        })
        expect(ctx.metadataSource).toEqual({ kind: 'HogQLQuery', query: 'select event from events' })
        expect(Array.isArray(ctx.groupAnalyticsTaxonomicGroups)).toBe(true)
        expect(Array.isArray(ctx.groupAnalyticsTaxonomicGroupNames)).toBe(true)
    })

    it('forwards consumer-supplied input fields', () => {
        const { result } = renderHook(
            () =>
                useTaxonomicGroupsContext({
                    eventNames: ['$pageview'],
                    suggestedFiltersLabel: 'Top picks',
                    hideBehavioralCohorts: true,
                    excludedProperties: { [TaxonomicFilterGroupType.Events]: ['blocked'] },
                    hogQLGlobals: { foo: 1 },
                    hogQLExpressionShowBreakdownLabelHint: true,
                }),
            { wrapper }
        )
        expect(result.current.eventNames).toEqual(['$pageview'])
        expect(result.current.suggestedFiltersLabel).toBe('Top picks')
        expect(result.current.hideBehavioralCohorts).toBe(true)
        expect(result.current.propertyFilters.excludedProperties).toEqual({
            [TaxonomicFilterGroupType.Events]: ['blocked'],
        })
        expect(result.current.hogQLExpressionComponentProps).toEqual({
            globals: { foo: 1 },
            showBreakdownLabelHint: true,
        })
    })

    it('memoises identity across renders when inputs are referentially stable', () => {
        const input = { eventNames: ['$pageview'] }
        const { result, rerender } = renderHook(() => useTaxonomicGroupsContext(input), { wrapper })
        const first = result.current
        rerender()
        expect(result.current).toBe(first)
    })

    it('feeds buildTaxonomicGroups end-to-end and produces a non-empty groups array', () => {
        const { result } = renderHook(() => useTaxonomicGroupsContext({ eventNames: ['$pageview'] }), {
            wrapper,
        })
        const groups = buildTaxonomicGroups(result.current)
        expect(groups.length).toBeGreaterThan(20)
        // Sanity-check a couple of well-known group types are present.
        const types = new Set(groups.map((g) => g.type))
        expect(types.has(TaxonomicFilterGroupType.Events)).toBe(true)
        expect(types.has(TaxonomicFilterGroupType.PersonProperties)).toBe(true)
        expect(types.has(TaxonomicFilterGroupType.Cohorts)).toBe(true)
        expect(types.has(TaxonomicFilterGroupType.HogQLExpression)).toBe(true)
        expect(types.has(TaxonomicFilterGroupType.SuggestedFilters)).toBe(true)
    })
})
