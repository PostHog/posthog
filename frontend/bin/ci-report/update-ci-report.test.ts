import { MARKER, parseSections, renderComment, slugify, STATUS_EMOJI, upsertSection } from './update-ci-report.mjs'

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

describe('ci-report section helper', () => {
    it('renders header and section blocks in fixed registry order regardless of write order', () => {
        // Written eager-graph -> dist-size -> bundle-size; registry order is the reverse.
        const rendered: string = renderComment(
            build([
                { id: 'eager-graph', status: 'ok', summary: 'e', body: 'EAGER' },
                { id: 'dist-size', status: 'ok', summary: 'd', body: 'DIST' },
                { id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' },
            ])
        )
        const headerOrder = [...rendered.matchAll(/- .+? \[(.+?)\]/g)].map((m) => m[1])
        expect(headerOrder).toEqual(['Bundle size', 'Eager graph', 'Dist folder size'])
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
        expect(get(sections, 'eager-graph').inner).toBe('## Eager graph\n\nNEW EAGER BODY')
        expect(get(sections, 'eager-graph').status).toBe('fail')
        expect(get(sections, 'eager-graph').summary).toBe('over budget')
    })

    it('round-trips status and summary so the header reflects sections written by other runs', () => {
        // A later run parses the persisted comment to rebuild the header — the status of a
        // section it did not write must survive encode/decode, or the summary list lies.
        const persisted: string = renderComment(
            build([{ id: 'bundle-size', status: 'warn', summary: '+120 KiB (2.1%)', body: 'x' }])
        )
        const reparsed: string = renderComment(parseSections(persisted))
        expect(reparsed).toContain(`- ${STATUS_EMOJI.warn} [Bundle size](#bundle-size) — +120 KiB (2.1%)`)
    })

    it.each([
        ['ok', STATUS_EMOJI.ok],
        ['warn', STATUS_EMOJI.warn],
        ['fail', STATUS_EMOJI.fail],
        ['info', STATUS_EMOJI.info],
        ['unknown-status', STATUS_EMOJI.info],
    ])('header maps status %s to its emoji', (status: string, emoji: string) => {
        const rendered: string = renderComment(build([{ id: 'bundle-size', status, summary: '', body: 'x' }]))
        expect(rendered).toContain(`- ${emoji} [Bundle size](#bundle-size)`)
    })

    it('omits the summary suffix when there is no summary', () => {
        const rendered: string = renderComment(build([{ id: 'bundle-size', status: 'ok', body: 'x' }]))
        expect(rendered).toContain(`- ${STATUS_EMOJI.ok} [Bundle size](#bundle-size)\n`)
        expect(rendered).not.toContain('[Bundle size](#bundle-size) —')
    })

    it.each([
        ['Bundle size', 'bundle-size'],
        ['Dist folder size', 'dist-folder-size'],
        ['🕸️ Eager graph', 'eager-graph'],
    ])('slugify(%s) matches the GitHub heading anchor %s', (title: string, slug: string) => {
        expect(slugify(title)).toBe(slug)
    })

    it('keeps an unregistered section instead of dropping it, ordered after known ones', () => {
        const withLegacy = build([{ id: 'bundle-size', status: 'ok', summary: '', body: 'x' }])
        withLegacy.set('legacy-check', { status: 'info', summary: 'old', inner: '## Legacy\n\nold body' })
        const rendered: string = renderComment(withLegacy)
        expect(rendered).toContain('old body')
        expect(rendered.indexOf('#bundle-size')).toBeLessThan(rendered.indexOf('legacy-check'))
    })
})
