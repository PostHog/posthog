import { billingByteReductionForDrops } from './logs-ingestion-consumer'

describe('billingByteReductionForDrops', () => {
    it.each<[string, number, number, number, number]>([
        // label, headerBytes, bytesDropped, bytesTotal, expected
        ['credits the dropped content fraction of the header', 1000, 600, 1000, 600],
        ['credits nothing when no rows were dropped', 1000, 0, 1000, 0],
        ['credits the full header when every row is dropped', 1000, 1000, 1000, 1000],
        ['credits nothing when bytesTotal is zero (unmeasurable)', 1000, 50, 0, 0],
        ['credits nothing when headerBytes is zero (unmeasurable)', 0, 50, 100, 0],
        ['caps the dropped fraction at 1 (defensive)', 1000, 1500, 1000, 1000],
        ['rounds to whole bytes (1000 × 1/3 = 333.33 → 333)', 1000, 1, 3, 333],
    ])('%s', (_label, headerBytes, bytesDropped, bytesTotal, expected) => {
        expect(billingByteReductionForDrops(headerBytes, bytesDropped, bytesTotal)).toBe(expected)
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
