import { FEATURE_FLAGS } from 'lib/constants'

import { InsightType } from '~/types'

import { addInsightToDashboardCreateOptions } from './addInsightToDashboardCreateOptions'

describe('addInsightToDashboardCreateOptions', () => {
    it.each([
        [false, false, false],
        [true, false, false],
        [false, true, false],
        [true, true, true],
    ])('offers metrics in quick-create with metrics=%s and builder=%s', (metrics, builder, offered) => {
        const { quickCreate, moreCreate } = addInsightToDashboardCreateOptions({
            dashboardId: 42,
            tileGroupKey: 'service-health',
            featureFlags: { [FEATURE_FLAGS.METRICS]: metrics, [FEATURE_FLAGS.METRICS_INSIGHT_BUILDER]: builder },
        })
        const option = quickCreate.find((item) => item.type === InsightType.METRICS)
        expect(!!option).toBe(offered)
        expect(moreCreate.some((item) => item.type === InsightType.METRICS)).toBe(false)
        if (option) {
            expect(option.url).toContain('dashboard=42')
            expect(option.url).toContain('tile_group=service-health')
        }
    })
})
