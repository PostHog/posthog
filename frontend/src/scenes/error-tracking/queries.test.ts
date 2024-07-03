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
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfInterval(timestamp, INTERVAL 1 minute), toStartOfInterval(subtractHours(now(), 0), INTERVAL 1 minute))), x), range(0, 60, 1)))`
        )
    })

    it('24h', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['24h'])
        expect(labels.length).toEqual(24)
        expect(labels[0]).toEqual(`'9 Jan, 2023 18:00 (UTC)'`)
        expect(labels[22]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)
        expect(labels[23]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfInterval(timestamp, INTERVAL 1 hour), toStartOfInterval(subtractHours(now(), 0), INTERVAL 1 hour))), x), range(0, 24, 1)))`
        )
    })

    it('7d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['7d'])
        expect(labels.length).toEqual(21)
        expect(labels[0]).toEqual(`'4 Jan, 2023 01:00 (UTC)'`)
        expect(labels[19]).toEqual(`'10 Jan, 2023 09:00 (UTC)'`)
        expect(labels[20]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfInterval(timestamp, INTERVAL 8 hour), toStartOfInterval(subtractHours(now(), 0), INTERVAL 8 hour))), x), range(0, 168, 8)))`
        )
    })

    it('14d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['14d'])
        expect(labels.length).toEqual(28)
        expect(labels[0]).toEqual(`'28 Dec, 2022 05:00 (UTC)'`)
        expect(labels[26]).toEqual(`'10 Jan, 2023 05:00 (UTC)'`)
        expect(labels[27]).toEqual(`'10 Jan, 2023 17:00 (UTC)'`) // start of hour

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfInterval(timestamp, INTERVAL 12 hour), toStartOfInterval(subtractHours(now(), 0), INTERVAL 12 hour))), x), range(0, 336, 12)))`
        )
    })

    it('90d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['90d'])
        expect(labels.length).toEqual(18)
        expect(labels[0]).toEqual(`'17 Oct, 2022 00:00 (UTC)'`)
        expect(labels[16]).toEqual(`'5 Jan, 2023 00:00 (UTC)'`)
        expect(labels[17]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of day

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfInterval(timestamp, INTERVAL 5 day), toStartOfInterval(subtractHours(now(), 0), INTERVAL 5 day))), x), range(0, 90, 5)))`
        )
    })

    it('180d', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['180d'])
        expect(labels.length).toEqual(18)
        expect(labels[0]).toEqual(`'24 Jul, 2022 00:00 (UTC)'`)
        expect(labels[16]).toEqual(`'31 Dec, 2022 00:00 (UTC)'`)
        expect(labels[17]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of day

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfInterval(timestamp, INTERVAL 10 day), toStartOfInterval(subtractHours(now(), 0), INTERVAL 10 day))), x), range(0, 180, 10)))`
        )
    })

    describe('offset', () => {
        it('1h', async () => {
            const { labels, data } = generateSparklineProps({ ...SPARKLINE_CONFIGURATIONS['1h'], offsetHours: 24 })
            expect(labels.length).toEqual(60)
            expect(labels[59]).toEqual(`'9 Jan, 2023 17:22 (UTC)'`) // one day earlier

            expect(data).toEqual(
                `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfInterval(timestamp, INTERVAL 1 minute), toStartOfInterval(subtractHours(now(), 24), INTERVAL 1 minute))), x), range(0, 60, 1)))`
            )
        })

        it('24h', async () => {
            const { labels, data } = generateSparklineProps({ ...SPARKLINE_CONFIGURATIONS['24h'], offsetHours: 24 })
            expect(labels.length).toEqual(24)
            expect(labels[23]).toEqual(`'9 Jan, 2023 17:00 (UTC)'`) // one day earlier

            expect(data).toEqual(
                `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfInterval(timestamp, INTERVAL 1 hour), toStartOfInterval(subtractHours(now(), 24), INTERVAL 1 hour))), x), range(0, 24, 1)))`
            )
        })
    })
})
