import { elapsed } from '../utils'

describe('elapsed', () => {
    it('returns a non-negative number', () => {
        const start = process.hrtime()
        const result = elapsed(start)
        expect(result).toBeGreaterThanOrEqual(0)
    })

    it('rounds to 3 decimal places', () => {
        const origHrtime = process.hrtime
        process.hrtime = ((startHr?: [number, number]) => {
            if (startHr) {
                return [1, 123456789] // 1.123456789s → should round to 1.123
            }
            return origHrtime()
        }) as typeof process.hrtime

        try {
            expect(elapsed([0, 0])).toBe(1.123)
        } finally {
            process.hrtime = origHrtime
        }
    })

    it('combines seconds and nanoseconds correctly', () => {
        const origHrtime = process.hrtime
        process.hrtime = ((startHr?: [number, number]) => {
            if (startHr) {
                return [5, 500000000] // 5.5s
            }
            return origHrtime()
        }) as typeof process.hrtime

        try {
            expect(elapsed([0, 0])).toBe(5.5)
        } finally {
            process.hrtime = origHrtime
        }
    })

    it('returns 0 for zero elapsed time', () => {
        const origHrtime = process.hrtime
        process.hrtime = ((startHr?: [number, number]) => {
            if (startHr) {
                return [0, 0]
            }
            return origHrtime()
        }) as typeof process.hrtime

        try {
            expect(elapsed([0, 0])).toBe(0)
        } finally {
            process.hrtime = origHrtime
        }
    })
})
