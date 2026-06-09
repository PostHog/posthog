import { billingByteReductionForDrops } from './logs-ingestion-consumer'

describe('billingByteReductionForDrops', () => {
    it('credits the dropped content fraction of the header', () => {
        // 60% of content dropped → credit 60% of the 1000-byte header.
        expect(billingByteReductionForDrops(1000, 600, 1000)).toBe(600)
    })

    it('credits nothing when no rows were dropped', () => {
        expect(billingByteReductionForDrops(1000, 0, 1000)).toBe(0)
    })

    it('credits the full header when every row is dropped', () => {
        expect(billingByteReductionForDrops(1000, 1000, 1000)).toBe(1000)
    })

    it('credits nothing when we cannot measure (no per-row bytes / no header)', () => {
        expect(billingByteReductionForDrops(1000, 50, 0)).toBe(0)
        expect(billingByteReductionForDrops(0, 50, 100)).toBe(0)
    })

    it('caps the dropped fraction at 1 (defensive)', () => {
        expect(billingByteReductionForDrops(1000, 1500, 1000)).toBe(1000)
    })

    it('rounds to whole bytes', () => {
        // 1000 × 1/3 = 333.33 → 333
        expect(billingByteReductionForDrops(1000, 1, 3)).toBe(333)
    })

    it('content- and record-weighted credits diverge on size-skewed drops (Tier 2 confidence signal)', () => {
        // header 10000; the dropped rows are 90% of content but only 10% of records (big rows dropped).
        const header = 10000
        const contentCredit = billingByteReductionForDrops(header, 9000, 10000) // 9000
        const recordCredit = billingByteReductionForDrops(header, 1, 10) // 1000
        // Large divergence ⇒ skewed batch ⇒ the content-weighted pro-rate is low-confidence.
        expect(Math.abs(contentCredit - recordCredit) / header).toBeGreaterThan(0.5)
    })

    it('content- and record-weighted credits agree on uniform drops (high confidence)', () => {
        const header = 10000
        // Uniform rows: dropping half the content == dropping half the records.
        expect(billingByteReductionForDrops(header, 5000, 10000)).toBe(billingByteReductionForDrops(header, 5, 10))
    })
})
