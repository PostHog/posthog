import { SPARKLINE_OPTIONS } from './errorTrackingLogic'
import { generateFormattedDateLabels } from './queries'

describe('generateFormattedDateLabels', () => {
    beforeAll(() => {
        jest.useFakeTimers().setSystemTime(new Date('2023-01-10 17:22:08'))
    })

    it('-1h', async () => {
        const labels = generateFormattedDateLabels(SPARKLINE_OPTIONS['-1h'])
        expect(labels.length).toEqual(60)
        expect(labels[0]).toEqual(`'10 Jan, 2023 16:22 (UTC)'`)
        expect(labels[58]).toEqual(`'10 Jan, 2023 17:20 (UTC)'`)
        expect(labels[59]).toEqual(`'10 Jan, 2023 17:21 (UTC)'`)
    })

    it('-24h', async () => {
        const labels = generateFormattedDateLabels(SPARKLINE_OPTIONS['-24h'])
        expect(labels.length).toEqual(24)
        expect(labels[0]).toEqual(`'9 Jan, 2023 17:00 (UTC)'`)
        expect(labels[22]).toEqual(`'10 Jan, 2023 15:00 (UTC)'`)
        expect(labels[23]).toEqual(`'10 Jan, 2023 16:00 (UTC)'`)

        // expect(generateFormattedDateLabels(SPARKLINE_OPTIONS['-24h'])).toEqual(1)
        // expect(generateFormattedDateLabels(SPARKLINE_OPTIONS['-7d'])).toEqual(1)
        // expect(generateFormattedDateLabels(SPARKLINE_OPTIONS['-14d'])).toEqual(1)
        // expect(generateFormattedDateLabels(SPARKLINE_OPTIONS['-90d'])).toEqual(1)
    })

    // it('accounts for an offset', async () => {
    //     expect(generateFormattedDateLabels({ ...SPARKLINE_OPTIONS['-1h'], offset: { value: 1, unit: 'day' } })).toEqual(
    //         1
    //     )
    //     expect(
    //         generateFormattedDateLabels({ ...SPARKLINE_OPTIONS['-24h'], offset: { value: 1, unit: 'day' } })
    //     ).toEqual(1)
    // })
})
