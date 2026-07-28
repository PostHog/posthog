import { resolveChartPlacements } from './chartPlacement'

describe('resolveChartPlacements', () => {
    const CHARTS = ['signups-drop', 'ret_7d']

    function placedIn(summary: string): string[] {
        return [...resolveChartPlacements(summary, CHARTS).inlineByOffset.values()]
    }

    it('places each reference where it appears in the prose', () => {
        const summary = 'Signups fell.\n\n[Daily signups](chart:signups-drop)\n\nAnd:\n\n[Retention](chart:ret_7d)'

        const { inlineByOffset, inlineIds } = resolveChartPlacements(summary, CHARTS)

        expect([...inlineByOffset.entries()]).toEqual([
            [summary.indexOf('[Daily signups]'), 'signups-drop'],
            [summary.indexOf('[Retention]'), 'ret_7d'],
        ])
        expect(inlineIds).toEqual(new Set(CHARTS))
    })

    it('places a reference that carries a link title', () => {
        // A regex over the raw markdown misses the title and calls the chart unreferenced, which
        // draws it twice: once here and again after the prose, firing its query twice.
        expect(placedIn('[Daily signups](chart:signups-drop "worth a look")')).toEqual(['signups-drop'])
    })

    it('places a reference link resolved through its definition', () => {
        // The renderer resolves `[label][id]` into the same anchor as an inline link, so a parse that
        // only reads `node.url` leaves the label here and draws the chart after the prose instead.
        expect(placedIn('[Daily signups][daily]\n\n[daily]: chart:signups-drop')).toEqual(['signups-drop'])
    })

    it('places a collapsed reference link', () => {
        // `[signups-drop][]` and the shortcut form carry the label as the identifier, which is the
        // shape a scout writing the id as the link text produces.
        expect(placedIn('[signups-drop][]\n\n[signups-drop]: chart:signups-drop')).toEqual(['signups-drop'])
    })

    it.each([
        ['inside a code span', 'Reference it as `[Daily signups](chart:signups-drop)` in the summary.'],
        ['inside a fenced block', '```\n[Daily signups](chart:signups-drop)\n```'],
        ['inside a table cell', '| Metric | Chart |\n| --- | --- |\n| Signups | [chart](chart:signups-drop) |'],
        ['inside a heading', '## [Daily signups](chart:signups-drop)'],
        ['for a chart the report does not have', '[Gone](chart:deleted-chart)'],
        // A chart is block-level and `LemonMarkdown` only unwraps the `<p>` around a paragraph whose
        // own children are references, so placing one the author formatted would put the chart inside
        // the `<strong>`/`<em>` and leave the paragraph around it.
        ['wrapped in bold', '**[Daily signups](chart:signups-drop)**'],
        ['wrapped in italics', '*[Daily signups](chart:signups-drop)*'],
    ])('leaves a reference %s to render after the prose', (_label, summary) => {
        expect(placedIn(summary)).toEqual([])
    })

    it.each([
        ['in a blockquote', '> [Daily signups](chart:signups-drop)'],
        ['in a list item', '- [Daily signups](chart:signups-drop)'],
    ])('still places a reference %s', (_label, summary) => {
        // The paragraph a chart reference sits in doesn't have to be top-level — the renderer unwraps
        // it just the same, and the surrounding block can hold the chart.
        expect(placedIn(summary)).toEqual(['signups-drop'])
    })

    it('places only the first reference to an id', () => {
        // Every extra copy re-runs the chart's query, and pointing back at a chart is what a repeated
        // reference reads as — not a request for a second one.
        const summary = '[Signups](chart:signups-drop) rose, then fell — see [signups again](chart:signups-drop).'

        const { inlineByOffset } = resolveChartPlacements(summary, CHARTS)

        expect([...inlineByOffset.entries()]).toEqual([[0, 'signups-drop']])
    })

    it.each([
        ['no summary', null],
        ['an empty summary', ''],
        ['a summary with no chart references', 'Signups fell. See [the dashboard](https://example.com).'],
    ])('places nothing for %s', (_label, summary) => {
        expect(resolveChartPlacements(summary, CHARTS).inlineIds).toEqual(new Set())
    })
})
