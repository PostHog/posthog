import { generateSparklineProps, parseSparklineSelection, SPARKLINE_CONFIGURATIONS } from './queries'

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
        expect(labels.length).toEqual(26)
        expect(labels[0]).toEqual(`'17 Jul, 2022 00:00 (UTC)'`)
        expect(labels[24]).toEqual(`'1 Jan, 2023 00:00 (UTC)'`)
        expect(labels[25]).toEqual(`'8 Jan, 2023 00:00 (UTC)'`) // start of week

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('week', toStartOfWeek(timestamp), toStartOfWeek(subtractHours(now(), 0)))), x), range(26)))`
        )
    })

    it('mStart', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['mStart'])
        expect(labels.length).toEqual(31)
        expect(labels[0]).toEqual(`'11 Dec, 2022 00:00 (UTC)'`) // goes back one full month
        expect(labels[29]).toEqual(`'9 Jan, 2023 00:00 (UTC)'`)
        expect(labels[30]).toEqual(`'10 Jan, 2023 00:00 (UTC)'`) // start of week

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('day', toStartOfDay(timestamp), toStartOfDay(subtractHours(now(), 0)))), x), range(31)))`
        )
    })

    it('yStart', async () => {
        const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['yStart'])
        expect(labels.length).toEqual(52)
        expect(labels[0]).toEqual(`'16 Jan, 2022 00:00 (UTC)'`) // goes back one full year
        expect(labels[50]).toEqual(`'1 Jan, 2023 00:00 (UTC)'`)
        expect(labels[51]).toEqual(`'8 Jan, 2023 00:00 (UTC)'`) // start of week

        expect(data).toEqual(
            `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('week', toStartOfWeek(timestamp), toStartOfWeek(subtractHours(now(), 0)))), x), range(52)))`
        )
    })

    describe('offset', () => {
        it('1h', async () => {
            const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['-1d1h'])
            expect(labels.length).toEqual(60)
            expect(labels[59]).toEqual(`'9 Jan, 2023 17:22 (UTC)'`) // one day earlier

            expect(data).toEqual(
                `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('minute', toStartOfMinute(timestamp), toStartOfMinute(subtractHours(now(), 24)))), x), range(60)))`
            )
        })

        it('24h', async () => {
            const { labels, data } = generateSparklineProps(SPARKLINE_CONFIGURATIONS['-1d24h'])
            expect(labels.length).toEqual(24)
            expect(labels[23]).toEqual(`'9 Jan, 2023 17:00 (UTC)'`) // one day earlier

            expect(data).toEqual(
                `reverse(arrayMap(x -> countEqual(groupArray(dateDiff('hour', toStartOfHour(timestamp), toStartOfHour(subtractHours(now(), 24)))), x), range(24)))`
            )
        })
    })
})

describe('parseSparklineSelection', () => {
    it('arbitrary values', async () => {
        expect(parseSparklineSelection('4y')).toEqual({ value: 48, displayAs: 'month' })
        expect(parseSparklineSelection('10m')).toEqual({ value: 10, displayAs: 'month' })
        expect(parseSparklineSelection('6w')).toEqual({ value: 6, displayAs: 'week' })
    })
})
