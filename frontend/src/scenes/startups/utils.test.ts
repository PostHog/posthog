import { getYCBatchOptions } from './utils'

let mockedToday = '2024-06-01'

// Mock dayjs to control "today" for testing
jest.mock('lib/dayjs', () => {
    const actualDayjs = jest.requireActual('lib/dayjs')
    return {
        dayjs: jest.fn().mockImplementation((date?: any) => {
            if (date) {
                return actualDayjs.dayjs(date)
            }
            // Return the mocked "today" when called without arguments
            return actualDayjs.dayjs(mockedToday)
        }),
    }
})

describe('getYCBatchOptions()', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('returns correct structure with placeholder and footer', () => {
        mockedToday = '2024-06-01' // Current batch (latest that started) is Winter 2024
        const result = getYCBatchOptions()

        expect(result[0]).toEqual({ label: 'Select your batch', value: '' })
        expect(result[result.length - 1]).toEqual({ label: 'Earlier batches', value: 'Earlier' })
        expect(result.length).toBeGreaterThan(2) // At least placeholder + some batches + footer
    })

    it('shows current batch and surrounding batches when in middle of timeline', () => {
        mockedToday = '2024-06-01' // Current batch (latest that started) is Winter 2024
        const result = getYCBatchOptions()

        const batchNames = result.slice(1, -1).map((option) => option.label) // Exclude placeholder and footer

        // Should include current, two future and all previous batches
        expect(batchNames).toContain('Winter 2024') // Current
        expect(batchNames).toContain('Summer 2024') // Future (Current + 1)
        expect(batchNames).toContain('Fall 2024') // Future (Current + 2)
        expect(batchNames).toContain('Winter 2023') // Past batch (Current - 1)
        expect(batchNames).toContain('Summer 2023') // Past batch (Current - 2)

        // Should not include far future batches
        expect(batchNames).not.toContain('Winter 2025') // Future (Current + 3)
    })

    it('handles when current batch is the newest batch', () => {
        mockedToday = '2027-10-01' // During Fall 2027 (newest batch)
        const result = getYCBatchOptions()

        const batchNames = result.slice(1, -1).map((option) => option.label)

        expect(batchNames).toContain('Fall 2027') // Current batch
        expect(batchNames).toContain('Summer 2027') // Previous batch (Current - 1)
        // Should include all remaining batches
        expect(batchNames.length).toBeGreaterThan(10)
    })

    it('shows correct batches for specific date scenarios', () => {
        mockedToday = '2024-01-08' // Exact start of Winter 2024
        const result1 = getYCBatchOptions()
        const batchNames1 = result1.slice(1, -1).map((option) => option.label)
        expect(batchNames1).toContain('Winter 2024') // Current batch
        expect(batchNames1).toContain('Summer 2024') // Future batch (Current + 1)
        expect(batchNames1).toContain('Fall 2024') // Future batch (Current + 2)

        mockedToday = '2024-01-07' // Day before Winter 2024 starts, so Summer 2023 is current
        const result2 = getYCBatchOptions()
        const batchNames2 = result2.slice(1, -1).map((option) => option.label)
        expect(batchNames2).toContain('Winter 2024') // Future batch (Current + 1)
        expect(batchNames2).toContain('Summer 2024') // Future batch (Current + 2)
        expect(batchNames2).toContain('Summer 2023') // Current batch
    })
})
