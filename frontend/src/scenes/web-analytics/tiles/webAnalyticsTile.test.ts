import { ProductTab } from 'scenes/web-analytics/common'

import { WebStatsBreakdown } from '~/queries/schema/schema-general'

import { comparisonTooltipText, getRowFilterability, toUtcOffsetFormat } from './WebAnalyticsTile'

describe('WebAnalyticsTile helpers', () => {
    describe('toUtcOffsetFormat', () => {
        it.each([
            [0, 'UTC'],
            [0.25, 'UTC+0:15'],
            [1, 'UTC+1'],
            [1.5, 'UTC+1:30'],
            [-0, 'UTC'],
            [-0.25, 'UTC-0:15'],
            [-1, 'UTC-1'],
            [-1.5, 'UTC-1:30'],
        ])('should format %d to %s', (minutes, expected) => {
            expect(toUtcOffsetFormat(minutes)).toEqual(expected)
        })
    })

    describe('comparisonTooltipText', () => {
        const formatNumber = (value: number): string => `${value}`

        it.each([
            [10, 0, true, 'Increased from 0 to 10 since last period'],
            [10, 5, true, 'Increased by 100% since last period (from 5 to 10)'],
            [5, 10, true, 'Decreased by 50% since last period (from 10 to 5)'],
            [5, 5, true, 'No change since last period (5)'],
            [10, null, true, null],
            [10, 5, false, null],
        ])('formats %s compared with %s', (current, previous, compare, expected) => {
            expect(comparisonTooltipText(current, previous, compare, formatNumber)).toEqual(expected)
        })
    })

    describe('getRowFilterability', () => {
        const baseArgs = {
            breakdownBy: WebStatsBreakdown.Page,
            breakdownValue: '/pricing',
            productTab: ProductTab.ANALYTICS,
            includeHost: false,
        }

        it.each([
            ['a breakdown backed by a property', {}, true, false],
            ['the host and path breakdown', { includeHost: true }, false, true],
            ['a page reports tile', { productTab: ProductTab.PAGE_REPORTS }, false, true],
            ['a breakdown with no property to filter', { breakdownBy: WebStatsBreakdown.PreviousPage }, false, false],
            [
                'a breakdown computed at query time',
                { breakdownBy: WebStatsBreakdown.FirstPageviewChannelType },
                false,
                false,
            ],
            ['a row with no value', { breakdownValue: undefined }, false, false],
            [
                'a compound breakdown',
                { breakdownBy: WebStatsBreakdown.Viewport, breakdownValue: '390x844' },
                true,
                false,
            ],
            [
                'a compound breakdown with an empty value',
                { breakdownBy: WebStatsBreakdown.Viewport, breakdownValue: '' },
                false,
                false,
            ],
            [
                'the utm source, medium and campaign breakdown',
                {
                    breakdownBy: WebStatsBreakdown.InitialUTMSourceMediumCampaign,
                    breakdownValue: 'google / cpc / spring',
                },
                true,
                false,
            ],
            ['the UTC timezone row', { breakdownBy: WebStatsBreakdown.Timezone, breakdownValue: '0' }, true, false],
        ])('%s', (_name, args, canFilter, expectsReason) => {
            const filterability = getRowFilterability({ ...baseArgs, ...args })

            expect(filterability.canFilter).toEqual(canFilter)
            expect(!filterability.canFilter && filterability.reason !== undefined).toEqual(expectsReason)
        })
    })
})
