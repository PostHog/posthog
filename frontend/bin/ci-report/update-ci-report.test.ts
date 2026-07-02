import { MARKER, parseSections, renderComment, STATUS_EMOJI, upsertSection } from './update-ci-report.mjs'

type SectionEntry = { status: string; summary: string; inner: string }
type SectionState = Map<string, SectionEntry>
type SectionInput = { id: string; status?: string; summary?: string; body: string }

function build(entries: SectionInput[]): SectionState {
    let sections: SectionState = new Map()
    for (const entry of entries) {
        sections = upsertSection(sections, entry) as SectionState
    }
    return sections
}

function get(sections: SectionState, id: string): SectionEntry {
    const entry = sections.get(id)
    if (!entry) {
        throw new Error(`expected section ${id} to be present`)
    }
    return entry
}

function sectionMeta(meta: { status: string; summary: string }): string {
    return Buffer.from(JSON.stringify(meta), 'utf-8').toString('base64')
}

describe('ci-report section helper', () => {
    it('renders collapsed section blocks in fixed registry order regardless of write order', () => {
        // Written eager-graph -> dist-size -> bundle-size; registry order is the reverse.
        const rendered: string = renderComment(
            build([
                { id: 'eager-graph', status: 'ok', summary: 'e', body: 'EAGER' },
                { id: 'dist-size', status: 'ok', summary: 'd', body: 'DIST' },
                { id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' },
            ])
        )
        const summaryOrder = [...rendered.matchAll(/<summary>.+?<b>(.+?)<\/b>/g)].map((m) => m[1])
        expect(summaryOrder).toEqual(['Bundle size', 'Eager graph', 'Dist folder size'])
        expect(rendered.indexOf('BUNDLE')).toBeLessThan(rendered.indexOf('EAGER'))
        expect(rendered.indexOf('EAGER')).toBeLessThan(rendered.indexOf('DIST'))
        expect(rendered.startsWith(MARKER)).toBe(true)
    })

    it('updating one section preserves the others and applies the new body', () => {
        const original = build([
            { id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE BODY' },
            { id: 'eager-graph', status: 'ok', summary: 'e', body: 'EAGER BODY' },
        ])
        const updated = upsertSection(original, {
            id: 'eager-graph',
            status: 'fail',
            summary: 'over budget',
            body: 'NEW EAGER BODY',
        })
        const sections = parseSections(renderComment(updated))
        expect(get(sections, 'bundle-size')).toEqual(get(original, 'bundle-size'))
        expect(get(sections, 'eager-graph')).toEqual({
            status: 'fail',
            summary: 'over budget',
            inner: 'NEW EAGER BODY',
        })
    })

    it.each([
        ['a plain body', 'plain body'],
        ['a multi-paragraph body', 'intro\n\n| a | b |\n| - | - |\n| 1 | 2 |'],
        [
            'a body ending in its own nested details block',
            'intro\n\n<details><summary>Largest files</summary>\n\n| file |\n\n</details>',
        ],
    ])(
        're-rendering a parsed comment is stable for %s (never wraps a section twice)',
        (_name: string, body: string) => {
            const rendered: string = renderComment(build([{ id: 'bundle-size', status: 'warn', summary: 's', body }]))
            expect(get(parseSections(rendered), 'bundle-size').inner).toBe(body)
            expect(renderComment(parseSections(rendered))).toBe(rendered)
        }
    )

    it('strips the in-body heading from sections written before the collapsible layout', () => {
        const legacy = [
            MARKER,
            '## 🤖 CI report',
            '',
            `<!-- ci-report:section:bundle-size:${sectionMeta({ status: 'ok', summary: 'b' })} -->`,
            '## Bundle size',
            '',
            'old body',
            '<!-- ci-report:section-end:bundle-size -->',
        ].join('\n')
        const sections = parseSections(legacy)
        expect(get(sections, 'bundle-size').inner).toBe('old body')
        expect(renderComment(sections)).not.toContain('## Bundle size')
    })

    it('round-trips status and summary so the collapsed line reflects sections written by other runs', () => {
        // A later run parses the persisted comment to re-render every section — the status
        // of a section it did not write must survive encode/decode, or the summary line lies.
        const persisted: string = renderComment(
            build([{ id: 'bundle-size', status: 'warn', summary: '+120 KiB (2.1%)', body: 'x' }])
        )
        const reparsed: string = renderComment(parseSections(persisted))
        expect(reparsed).toContain(`<summary>${STATUS_EMOJI.warn} <b>Bundle size</b> — +120 KiB (2.1%)</summary>`)
    })

    it.each([
        ['ok', STATUS_EMOJI.ok],
        ['warn', STATUS_EMOJI.warn],
        ['fail', STATUS_EMOJI.fail],
        ['info', STATUS_EMOJI.info],
        ['unknown-status', STATUS_EMOJI.info],
    ])('collapsed line maps status %s to its emoji', (status: string, emoji: string) => {
        const rendered: string = renderComment(build([{ id: 'bundle-size', status, summary: '', body: 'x' }]))
        expect(rendered).toContain(`<summary>${emoji} <b>Bundle size</b>`)
    })

    it('omits the summary suffix when there is no summary', () => {
        const rendered: string = renderComment(build([{ id: 'bundle-size', status: 'ok', body: 'x' }]))
        expect(rendered).toContain(`<summary>${STATUS_EMOJI.ok} <b>Bundle size</b></summary>`)
        expect(rendered).not.toContain('<b>Bundle size</b> —')
    })

    it('keeps an unregistered section instead of dropping it, ordered after known ones', () => {
        const withLegacy = build([{ id: 'bundle-size', status: 'ok', summary: '', body: 'x' }])
        withLegacy.set('legacy-check', { status: 'info', summary: 'old', inner: 'old body' })
        const rendered: string = renderComment(withLegacy)
        expect(rendered).toContain('old body')
        expect(rendered.indexOf('<b>Bundle size</b>')).toBeLessThan(rendered.indexOf('legacy-check'))
    })
})
