import { sampleForContext } from './sampleForContext'

describe('sampleForContext', () => {
    it('preserves structure and keys of small payloads', () => {
        const rendered = sampleForContext({ role: 'user', content: 'hi', nested: { a: [1, 2] } })

        expect(JSON.parse(rendered)).toEqual({ role: 'user', content: 'hi', nested: { a: [1, 2] } })
    })

    it('truncates long strings but keeps the key', () => {
        const rendered = sampleForContext({ content: 'x'.repeat(5000) })

        const parsed = JSON.parse(rendered)
        expect(parsed.content).toHaveLength(280 + '… (truncated)'.length)
        expect(parsed.content).toContain('… (truncated)')
    })

    it('keeps the head and tail of long arrays with a marker in between', () => {
        const rendered = sampleForContext(Array.from({ length: 50 }, (_, i) => ({ index: i })))

        const parsed = JSON.parse(rendered)
        expect(parsed).toHaveLength(6)
        expect(parsed[0]).toEqual({ index: 0 })
        expect(parsed[4]).toEqual('… (45 more items)')
        expect(parsed[5]).toEqual({ index: 49 })
    })

    it('uses the singular noun when exactly one array item is omitted', () => {
        const rendered = sampleForContext(Array.from({ length: 6 }, (_, i) => ({ index: i })))

        const parsed = JSON.parse(rendered)
        expect(parsed[4]).toEqual('… (1 more item)')
    })

    it('caps the total rendered length', () => {
        const rendered = sampleForContext(
            Array.from({ length: 5 }, () => ({ blob: 'y'.repeat(279), more: 'z'.repeat(279) }))
        )

        expect(rendered.length).toBeLessThanOrEqual(8000 + '\n… (sample truncated)'.length)
    })
})
