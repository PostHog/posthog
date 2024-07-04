import { generateSparklineProps, SPARKLINE_CONFIGURATIONS } from './queries'

describe('generateSparklineProps', () => {
    beforeAll(() => {
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    it('1h', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['1h'])
        expect(labels.length).toEqual(60)
        expect(labels[0]).toEqual(`'10 Jan, 2023 16:23 (UTC)'`)
        expect(labels[58]).toEqual(`'10 Jan, 2023 17:21 (UTC)'`)
        expect(labels[59]).toEqual(`'10 Jan, 2023 17:22 (UTC)'`) // start of minute

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfMinute(timestamp), toStartOfMinute(subtractHours(now(), 0)))), x), range(60)))`
        )
    })

    it('24h', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['24h'])
        expect(labels.length).toEqual(24)
        expect(labels[0]).toEqual(`'9 Jan, 2023 18:00 (UTC)'`)
        expect(labels[22]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[23]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(subtractHours(now(), 0)))), x), range(24)))`
        )
    })

    it('7d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['7d'])
        expect(labels.length).toEqual(168)
        expect(labels[0]).toEqual(`'3 Jan, 2023 18:00 (UTC)'`)
        expect(labels[166]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[167]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(subtractHours(now(), 0)))), x), range(168)))`
        )
    })

    it('14d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['14d'])
        expect(labels.length).toEqual(336)
        expect(labels[0]).toEqual(`'27 Dec, 2022 18:00 (UTC)'`)
        expect(labels[334]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[335]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(subtractHours(now(), 0)))), x), range(336)))`
        )
    })

    it('90d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['90d'])
        expect(labels.length).toEqual(90)
        expect(labels[0]).toEqual(`'13 Oct, 2022 00:00 (UTC)'`)
        expect(labels[88]).toEqual(`'9 Jan, 2023 00:00 (UTC)'`)
        expect(labels[89]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of day

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfDay(timestamp), toStartOfDay(subtractHours(now(), 0)))), x), range(90)))`
        )
    })

    it('180d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['180d'])
        expect(labels.length).toEqual(180)
        expect(labels[0]).toEqual(`'15 Jul, 2022 00:00 (UTC)'`)
        expect(labels[178]).toEqual(`'9 Jan, 2023 00:00 (UTC)'`)
        expect(labels[179]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of day

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfDay(timestamp), toStartOfDay(subtractHours(now(), 0)))), x), range(180)))`
        )
    })
})
