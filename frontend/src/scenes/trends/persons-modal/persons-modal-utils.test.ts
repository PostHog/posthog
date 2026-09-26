import { BREAKDOWN_BASELINE_STRING_LABEL } from 'scenes/insights/utils'

import { ActorsQuery, BreakdownItem, FunnelsActorsQuery, NodeKind } from '~/queries/schema/schema-general'

import {
    funnelBreakdownSelectValue,
    funnelStepBreakdownFromSelectValue,
    personsModalExportContext,
} from './persons-modal-utils'

describe('persons modal funnel breakdown helpers', () => {
    it('exports a direct actors query with its attribution filters and without recordings', () => {
        const query: ActorsQuery = {
            kind: NodeKind.ActorsQuery,
            select: ['actor', 'matched_recordings'],
            orderBy: ['id'],
            search: 'example',
            source: {
                kind: NodeKind.MarketingAnalyticsActorsQuery,
                source: {
                    kind: NodeKind.MarketingAnalyticsTableQuery,
                    properties: [],
                    dateRange: { date_from: '-7d' },
                },
                conversionGoalId: 'purchases',
                breakdown: { value: 'winter-sale', source: 'google' },
            },
        }
        expect(personsModalExportContext(query, '')).toEqual({ source: { ...query, select: ['actor'] } })
        expect(personsModalExportContext(null, '/api/projects/1/persons')).toEqual({ path: '/api/projects/1/persons' })
    })

    const options: BreakdownItem[] = [
        { label: 'Baseline', value: BREAKDOWN_BASELINE_STRING_LABEL },
        { label: 'Chrome', value: 'Chrome' },
        { label: 'Chrome, Mac OS X', value: '["Chrome","Mac OS X"]' },
        { label: 'my cohort', value: 2 },
    ]

    describe('funnelStepBreakdownFromSelectValue', () => {
        it.each<[string | number | null, FunnelsActorsQuery['funnelStepBreakdown']]>([
            [BREAKDOWN_BASELINE_STRING_LABEL, null],
            [null, null],
            ['Chrome', 'Chrome'],
            [2, 2],
            ['["Chrome","Mac OS X"]', ['Chrome', 'Mac OS X']],
            ['[not json', '[not json'],
        ])('maps selection %p to funnelStepBreakdown %p', (selection, expected) => {
            expect(funnelStepBreakdownFromSelectValue(selection)).toEqual(expected)
        })
    })

    describe('funnelBreakdownSelectValue', () => {
        it.each<[FunnelsActorsQuery['funnelStepBreakdown'] | undefined, string | number | null]>([
            [null, BREAKDOWN_BASELINE_STRING_LABEL],
            [undefined, BREAKDOWN_BASELINE_STRING_LABEL],
            ['Chrome', 'Chrome'],
            [['Chrome'], 'Chrome'], // single-element arrays match their unwrapped option
            [['Chrome', 'Mac OS X'], '["Chrome","Mac OS X"]'],
            ['2', 2], // numeric/string drift between result values and option values
            ['Safari', null], // no matching option must not fall back to Baseline
        ])('maps funnelStepBreakdown %p to selection %p', (funnelStepBreakdown, expected) => {
            expect(funnelBreakdownSelectValue(funnelStepBreakdown, options)).toEqual(expected)
        })
    })
})
