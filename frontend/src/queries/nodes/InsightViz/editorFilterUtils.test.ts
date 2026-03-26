import { BreakdownFilter } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyGroupFilter, PropertyOperator } from '~/types'

import { getBreakdownSummary, getFiltersSummary, getSeriesSummary } from './editorFilterUtils'

describe('editorFilterUtils', () => {
    describe('getSeriesSummary', () => {
        it.each([
            [null, null],
            [undefined, null],
            [[], null],
        ])('returns null for %s', (input, expected) => {
            expect(getSeriesSummary(input)).toBe(expected)
        })

        it('prefers custom_name over event and name', () => {
            expect(getSeriesSummary([{ custom_name: 'My series', event: '$pageview', name: 'fallback' }])).toBe(
                'My series'
            )
        })

        it('falls back to event', () => {
            expect(getSeriesSummary([{ event: '$pageview', name: 'fallback' }])).toBe('$pageview')
        })

        it('falls back to name', () => {
            expect(getSeriesSummary([{ name: 'some_action' }])).toBe('some_action')
        })

        it('joins multiple series', () => {
            expect(getSeriesSummary([{ event: 'signed_up' }, { event: '$pageview' }])).toBe('signed_up, $pageview')
        })
    })

    describe('getFiltersSummary', () => {
        it.each([
            [null, null],
            [undefined, null],
            [[], null],
        ])('returns null for %s', (input, expected) => {
            expect(getFiltersSummary(input)).toBe(expected)
        })

        it('returns property keys from flat array', () => {
            expect(
                getFiltersSummary([
                    { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
                    { key: '$os', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
                ])
            ).toBe('$browser, $os')
        })

        it('extracts keys from PropertyGroupFilter', () => {
            const filter: PropertyGroupFilter = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [{ key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact }],
                    },
                ],
            }
            expect(getFiltersSummary(filter)).toBe('$browser')
        })

        it('skips nested PropertyGroupFilterValue items', () => {
            const filter: PropertyGroupFilter = {
                type: FilterLogicalOperator.And,
                values: [
                    {
                        type: FilterLogicalOperator.And,
                        values: [
                            { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact },
                            { type: FilterLogicalOperator.Or, values: [] },
                        ],
                    },
                ],
            }
            expect(getFiltersSummary(filter)).toBe('$browser')
        })
    })

    describe('getBreakdownSummary', () => {
        it.each<[BreakdownFilter | null | undefined, null]>([
            [null, null],
            [undefined, null],
            [{}, null],
        ])('returns null for %s', (input, expected) => {
            expect(getBreakdownSummary(input)).toBe(expected)
        })

        it('returns property names from breakdowns array', () => {
            const filter: BreakdownFilter = {
                breakdowns: [{ property: '$browser' }, { property: '$os' }],
            }
            expect(getBreakdownSummary(filter)).toBe('$browser, $os')
        })

        it('returns string breakdown directly', () => {
            const filter: BreakdownFilter = { breakdown: '$browser' }
            expect(getBreakdownSummary(filter)).toBe('$browser')
        })

        it('prefers breakdowns over breakdown', () => {
            const filter: BreakdownFilter = {
                breakdowns: [{ property: '$os' }],
                breakdown: '$browser',
            }
            expect(getBreakdownSummary(filter)).toBe('$os')
        })
    })
})
