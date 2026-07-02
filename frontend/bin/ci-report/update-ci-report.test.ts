import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { MARKER, parseSections, postSection, renderComment, STATUS_EMOJI, upsertSection } from './update-ci-report.mjs'

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

function legacyComment(summary: string, body = 'old body'): string {
    return [
        MARKER,
        '## 🤖 CI report',
        '',
        `<!-- ci-report:section:bundle-size:${sectionMeta({ status: 'ok', summary })} -->`,
        '## Bundle size',
        '',
        body,
        '<!-- ci-report:section-end:bundle-size -->',
    ].join('\n')
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

    it.each([
        ['a summary containing newlines', 'over\nbudget', ' — over budget'],
        ['a null summary', null as unknown as string, ''],
        ['a whitespace-only summary', ' \n ', ''],
    ])(
        'renders %s on a single line so the wrapper survives re-parse',
        (_name: string, summary: string, suffix: string) => {
            const rendered: string = renderComment(build([{ id: 'bundle-size', status: 'ok', summary, body: 'x' }]))
            expect(rendered).toContain(`<summary>${STATUS_EMOJI.ok} <b>Bundle size</b>${suffix}</summary>`)
            expect(renderComment(parseSections(rendered))).toBe(rendered)
        }
    )

    it('normalizes a multi-line summary replayed from persisted meta, not just fresh upserts', () => {
        const rendered: string = renderComment(parseSections(legacyComment('line1\nline2')))
        expect(rendered).toContain('<b>Bundle size</b> — line1 line2</summary>')
        expect(renderComment(parseSections(rendered))).toBe(rendered)
    })

    it('strips the in-body heading from sections written before the collapsible layout', () => {
        const sections = parseSections(legacyComment('b'))
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

    describe('postSection concurrency', () => {
        type StoredComment = { id: number; body: string }
        // An in-memory GitHub issue-comments API — the network is the boundary being
        // faked; assertions are on the surviving comment state, not call choreography.
        function fakeGitHub(initialBodies: string[] = []): {
            comments: StoredComment[]
            afterWrite: { fn: (() => void) | null }
        } {
            let nextId = 100
            const comments: StoredComment[] = initialBodies.map((body) => ({ id: ++nextId, body }))
            const afterWrite: { fn: (() => void) | null } = { fn: null }
            const json = (data: unknown): Response =>
                ({ ok: true, status: 200, json: async () => data, text: async () => '' }) as unknown as Response
            globalThis.fetch = async (url: RequestInfo | URL, options: RequestInit = {}): Promise<Response> => {
                const method = options.method ?? 'GET'
                const fireAfterWrite = (): void => {
                    afterWrite.fn?.()
                    afterWrite.fn = null
                }
                if (method === 'GET') {
                    const page = Number(new URL(String(url)).searchParams.get('page') ?? '1')
                    return json(page === 1 ? [...comments] : [])
                }
                if (method === 'POST') {
                    comments.push({ id: ++nextId, body: JSON.parse(String(options.body)).body })
                    fireAfterWrite()
                    return json(comments.at(-1))
                }
                const id = Number(String(url).split('/').pop())
                if (method === 'PATCH') {
                    const target = comments.find((c) => c.id === id)
                    if (target) {
                        target.body = JSON.parse(String(options.body)).body
                    }
                    fireAfterWrite()
                    return json({})
                }
                if (method === 'DELETE') {
                    comments.splice(
                        comments.findIndex((c) => c.id === id),
                        1
                    )
                    return {
                        ok: true,
                        status: 204,
                        json: async () => null,
                        text: async () => '',
                    } as unknown as Response
                }
                return {
                    ok: false,
                    status: 404,
                    json: async () => ({}),
                    text: async () => 'not found',
                } as unknown as Response
            }
            return { comments, afterWrite }
        }

        const realFetch = globalThis.fetch
        let tmpDir: string

        beforeAll(() => {
            tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'ci-report-test-'))
            const eventPath = path.join(tmpDir, 'event.json')
            fs.writeFileSync(eventPath, JSON.stringify({ pull_request: { number: 1 } }))
            process.env.GITHUB_TOKEN = 'test-token'
            process.env.GITHUB_REPOSITORY = 'PostHog/posthog'
            process.env.GITHUB_EVENT_PATH = eventPath
        })

        afterAll(() => {
            globalThis.fetch = realFetch
            fs.rmSync(tmpDir, { recursive: true, force: true })
            delete process.env.GITHUB_TOKEN
            delete process.env.GITHUB_REPOSITORY
            delete process.env.GITHUB_EVENT_PATH
        })

        const opts = { retryDelayMs: 0 }

        it('creates the comment when none exists, then a second writer joins it', async () => {
            const github = fakeGitHub()
            await postSection({ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }, opts)
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body)
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph'])
        })

        it('retries when a concurrent writer clobbers the section, keeping both', async () => {
            // The other writer read the comment before our PATCH landed and wrote after
            // it — its render is missing our section. The verify pass must catch that
            // and re-merge, or cross-workflow sections silently vanish.
            const github = fakeGitHub([
                renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])),
            ])
            const clobber = renderComment(
                build([
                    { id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' },
                    { id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' },
                ])
            )
            github.afterWrite.fn = () => {
                github.comments[0].body = clobber
            }
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body)
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph', 'dist-size'])
            expect(get(sections as SectionState, 'eager-graph').inner).toBe('EAGER')
        })

        it('merges duplicate report comments into the oldest and deletes the rest', async () => {
            const github = fakeGitHub([
                renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])),
                renderComment(build([{ id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' }])),
            ])
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body)
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph', 'dist-size'])
        })
    })
})
