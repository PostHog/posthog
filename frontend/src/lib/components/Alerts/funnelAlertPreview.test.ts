import { deriveFunnelAlertPreview } from './funnelAlertPreview'
import { AlertConfig } from './types'

const FUNNEL_CONFIG: AlertConfig = { type: 'FunnelsAlertConfig', funnel_step: null, metric: 'conversion_from_start' }

describe('deriveFunnelAlertPreview', () => {
    it('reads the latest period of a trends funnel as the conversion rate', () => {
        const insightData = { result: [{ count: 3, data: [10, 25, 40], days: ['d1', 'd2', 'd3'] }] }
        const preview = deriveFunnelAlertPreview(insightData, FUNNEL_CONFIG, { lower: 50 }, true)
        expect(preview).toEqual({
            status: 'ok',
            isBreakdown: false,
            hasBounds: true,
            values: [{ label: null, rate: 40, breaching: true }],
        })
    })

    it('yields one value per breakdown for a trends funnel and drops previous-period rows', () => {
        const insightData = {
            result: [
                { data: [10, 40], breakdown_value: ['Chrome'], compare_label: 'current' },
                { data: [5, 20], breakdown_value: ['Safari'], compare_label: 'current' },
                { data: [8, 30], breakdown_value: ['Chrome'], compare_label: 'previous' },
            ],
        }
        const preview = deriveFunnelAlertPreview(insightData, FUNNEL_CONFIG, null, true)
        expect(preview).toMatchObject({
            status: 'ok',
            isBreakdown: true,
            values: [
                { label: 'Chrome', rate: 40 },
                { label: 'Safari', rate: 20 },
            ],
        })
    })

    it('still reads a steps funnel as conversion at the configured step', () => {
        const insightData = { result: [{ count: 100 }, { count: 40 }] }
        const preview = deriveFunnelAlertPreview(insightData, FUNNEL_CONFIG, null, false)
        expect(preview).toMatchObject({ status: 'ok', isBreakdown: false, values: [{ rate: 40 }] })
    })
})
