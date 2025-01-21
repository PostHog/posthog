import { constructSparklineConfig, SPARKLINE_CONFIGURATIONS } from './errorTrackingLogic'
import { sparklineLabels } from './utils'

describe('generateSparklineProps', () => {
    beforeAll(() => {
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    it('1h', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['1h'])
        expect(labels.length).toEqual(60)
        expect(labels[0]).toEqual(`'10 Jan, 2023 16:23 (UTC)'`)
        expect(labels[58]).toEqual(`'10 Jan, 2023 17:21 (UTC)'`)
        expect(labels[59]).toEqual(`'10 Jan, 2023 17:22 (UTC)'`) // start of minute
    })

    it('24h', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['24h'])
        expect(labels.length).toEqual(24)
        expect(labels[0]).toEqual(`'9 Jan, 2023 18:00 (UTC)'`)
        expect(labels[22]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[23]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour
    })

    it('7d', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['7d'])
        expect(labels.length).toEqual(168)
        expect(labels[0]).toEqual(`'3 Jan, 2023 18:00 (UTC)'`)
        expect(labels[166]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[167]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour
    })

    it('14d', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['14d'])
        expect(labels.length).toEqual(336)
        expect(labels[0]).toEqual(`'27 Dec, 2022 18:00 (UTC)'`)
        expect(labels[334]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[335]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour
    })

    it('90d', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['90d'])
        expect(labels.length).toEqual(90)
        expect(labels[0]).toEqual(`'13 Oct, 2022 00:00 (UTC)'`)
        expect(labels[88]).toEqual(`'9 Jan, 2023 00:00 (UTC)'`)
        expect(labels[89]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of day
    })

    it('180d', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['180d'])
        expect(labels.length).toEqual(26)
        expect(labels[0]).toEqual(`'17 Jul, 2022 00:00 (UTC)'`)
        expect(labels[24]).toEqual(`'1 Jan, 2023 00:00 (UTC)'`)
        expect(labels[25]).toEqual(`'8 Jan, 2023 00:00 (UTC)'`) // start of week
    })

    it('mStart', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['mStart'])
        expect(labels.length).toEqual(31)
        expect(labels[0]).toEqual(`'11 Dec, 2022 00:00 (UTC)'`) // goes back one full month
        expect(labels[29]).toEqual(`'9 Jan, 2023 00:00 (UTC)'`)
        expect(labels[30]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of week
    })

    it('yStart', async () => {
        const labels = sparklineLabels(SPARKLINE_CONFIGURATIONS['yStart'])
        expect(labels.length).toEqual(52)
        expect(labels[0]).toEqual(`'16 Jan, 2022 00:00 (UTC)'`) // goes back one full year
        expect(labels[50]).toEqual(`'1 Jan, 2023 00:00 (UTC)'`)
        expect(labels[51]).toEqual(`'8 Jan, 2023 00:00 (UTC)'`) // start of week
    })
})

describe('constructSparklineConfig', () => {
    it('arbitrary values', async () => {
        expect(constructSparklineConfig('4y')).toEqual({ value: 48, interval: 'month' })
        expect(constructSparklineConfig('10m')).toEqual({ value: 10, interval: 'month' })
        expect(constructSparklineConfig('6w')).toEqual({ value: 6, interval: 'week' })
    })
})
