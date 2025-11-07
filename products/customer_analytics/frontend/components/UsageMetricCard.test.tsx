import { IconTrending } from '@posthog/icons'

import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'

import { UsageMetric } from '~/queries/schema/schema-general'

import { getMetricTooltip, getTrendFromPercentageChange } from './UsageMetricCard'

describe('getTrendFromPercentageChange', () => {
    it('returns undefined when change is null', () => {
        const result = getTrendFromPercentageChange(null)
        expect(result).toBeUndefined()
    })

    it('returns flat trend when change is 0', () => {
        const result = getTrendFromPercentageChange(0)
        expect(result).toEqual({
            icon: IconTrendingFlat,
            color: getColorVar('muted'),
            tooltip: 'unchanged',
        })
    })

    it('returns positive trend when change is positive', () => {
        const result = getTrendFromPercentageChange(0.25)
        expect(result).toEqual({
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.25%',
        })
    })

    it('returns positive trend with small percentage', () => {
        const result = getTrendFromPercentageChange(0.05)
        expect(result).toEqual({
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.05%',
        })
    })

    it('returns negative trend when change is negative', () => {
        const result = getTrendFromPercentageChange(-0.15)
        expect(result).toEqual({
            icon: IconTrendingDown,
            color: getColorVar('danger'),
            tooltip: 'decreased by 0.15%',
        })
    })

    it('returns negative trend with large percentage', () => {
        const result = getTrendFromPercentageChange(-0.85)
        expect(result).toEqual({
            icon: IconTrendingDown,
            color: getColorVar('danger'),
            tooltip: 'decreased by 0.85%',
        })
    })

    it('handles very small positive changes', () => {
        const result = getTrendFromPercentageChange(0.001)
        expect(result).toEqual({
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.001%',
        })
    })

    it('handles very small negative changes', () => {
        const result = getTrendFromPercentageChange(-0.001)
        expect(result).toEqual({
            icon: IconTrendingDown,
            color: getColorVar('danger'),
            tooltip: 'decreased by 0.001%',
        })
    })
})

describe('getMetricTooltip', () => {
    const baseMetric: UsageMetric = {
        id: 'revenue',
        name: 'Revenue',
        value: 50000,
        previous: 40000,
        change_from_previous_pct: 0.25,
        interval: 30,
        format: 'currency',
        display: 'number',
    }

    it('returns basic tooltip when trend is undefined', () => {
        const result = getMetricTooltip(baseMetric as UsageMetric, undefined)
        expect(result).toBe('Revenue: 50,000')
    })

    it('returns basic tooltip when trend has no tooltip', () => {
        const trend = {
            icon: IconTrendingFlat,
            color: getColorVar('muted'),
            tooltip: null,
        }
        const result = getMetricTooltip(baseMetric as UsageMetric, trend)
        expect(result).toBe('Revenue: 50,000')
    })

    it('returns full tooltip when trend has tooltip for increase', () => {
        const trend = {
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.25%',
        }
        const result = getMetricTooltip(baseMetric as UsageMetric, trend)
        expect(result).toBe('Revenue: increased by 0.25%, to 50,000 from 40,000')
    })

    it('returns full tooltip when trend has tooltip for decrease', () => {
        const metric: UsageMetric = {
            ...baseMetric,
            value: 35000,
            previous: 40000,
            change_from_previous_pct: -0.125,
        }
        const trend = {
            icon: IconTrendingDown,
            color: getColorVar('danger'),
            tooltip: 'decreased by 0.125%',
        }
        const result = getMetricTooltip(metric, trend)
        expect(result).toBe('Revenue: decreased by 0.125%, to 35,000 from 40,000')
    })

    it('returns full tooltip when trend has tooltip for unchanged', () => {
        const metric: UsageMetric = {
            ...baseMetric,
            value: 40000,
            previous: 40000,
            change_from_previous_pct: 0,
        }
        const trend = {
            icon: IconTrendingFlat,
            color: getColorVar('muted'),
            tooltip: 'unchanged',
        }
        const result = getMetricTooltip(metric, trend)
        expect(result).toBe('Revenue: unchanged, to 40,000 from 40,000')
    })

    it('handles different metric names', () => {
        const metric: UsageMetric = {
            ...baseMetric,
            name: 'Active Users',
        }
        const trend = {
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.25%',
        }
        const result = getMetricTooltip(metric, trend)
        expect(result).toBe('Active Users: increased by 0.25%, to 50,000 from 40,000')
    })

    it('handles large numbers', () => {
        const metric: UsageMetric = {
            ...baseMetric,
            value: 1234567,
            previous: 1000000,
        }
        const trend = {
            icon: IconTrending,
            color: getColorVar('success'),
            tooltip: 'increased by 0.2345%',
        }
        const result = getMetricTooltip(metric, trend)
        expect(result).toBe('Revenue: increased by 0.2345%, to 1,234,567 from 1,000,000')
    })
})
