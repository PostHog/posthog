import { metricMarkdownConverter, parseMarkdownPaste } from './metricMarkdown'

describe('metricMarkdown', () => {
    it('round-trips a sql fence with its language tag', () => {
        const markdown = 'Run this query:\n\n```sql\nSELECT count() FROM events\n```'

        const doc = metricMarkdownConverter.markdownToDoc(markdown)
        const codeBlock = doc.content?.find((node) => node.type === 'codeBlock')
        expect(codeBlock?.attrs?.language).toBe('sql')

        const serialized = metricMarkdownConverter.docToMarkdown(doc)
        expect(serialized).toContain('```sql')
        expect(serialized).toContain('SELECT count() FROM events')
        expect(metricMarkdownConverter.isRoundTripSafe(markdown)).toBe(true)
    })

    it('keeps images out of the schema and flags them as not round-trip safe', () => {
        const agentAuthored = '# Metric\n\n![chart](https://example.com/chart.png)'

        const doc = metricMarkdownConverter.markdownToDoc(agentAuthored)
        expect(JSON.stringify(doc)).not.toContain('"type":"image"')
        expect(metricMarkdownConverter.isRoundTripSafe(agentAuthored)).toBe(false)
    })

    it.each([
        ['headings and lists', '## Steps\n\n1. Count signups\n2. Divide by visitors', 'formatted'],
        ['a sql fence', 'Run:\n\n```sql\nSELECT count() FROM events\n```', 'formatted'],
        ['plain prose', 'Count every person who signed up this week.', 'plain'],
        ['an image the schema drops', '# Metric\n\n![chart](https://example.com/chart.png)', 'lossy'],
    ])('pastes %s without losing words', (_case, pasted, expected) => {
        const result = parseMarkdownPaste(pasted)
        const outcome = result.kind === 'formatted' ? 'formatted' : result.lossy ? 'lossy' : 'plain'
        expect(outcome).toEqual(expected)
    })
})
