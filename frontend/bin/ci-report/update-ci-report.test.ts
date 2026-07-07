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
    // The script narrates its progress to the CI job log via console.info/warn;
    // exercising it in jest would dump that narration into the test output.
    beforeEach(() => {
        jest.spyOn(console, 'info').mockImplementation(() => {})
        jest.spyOn(console, 'warn').mockImplementation(() => {})
    })
    afterEach(() => {
        jest.restoreAllMocks()
    })

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
        type StoredComment = { id: number; body: string; author: string }
        type FireOnceHook = { fn: (() => void) | null }
        // An in-memory GitHub issue-comments API — the network is the boundary being
        // faked; assertions are on the surviving comment state, not call choreography.
        // Missing-id writes 404 like real GitHub so the conflict paths are expressible;
        // the fire-once hooks inject a concurrent writer at the two race points.
        function fakeGitHub(initial: Array<{ body: string; author?: string }> = []): {
            comments: StoredComment[]
            afterNextWrite: FireOnceHook
            afterNextRead: FireOnceHook
            state: { patches: number; denyDeletes: boolean }
        } {
            let nextId = 100
            const comments: StoredComment[] = initial.map(({ body, author }) => ({
                id: ++nextId,
                body,
                author: author ?? 'github-actions[bot]',
            }))
            const afterNextWrite: FireOnceHook = { fn: null }
            const afterNextRead: FireOnceHook = { fn: null }
            const state = { patches: 0, denyDeletes: false }
            const fireOnce = (hook: FireOnceHook): void => {
                const fn = hook.fn
                hook.fn = null
                fn?.()
            }
            const json = (data: unknown): Response =>
                ({ ok: true, status: 200, json: async () => data, text: async () => '' }) as unknown as Response
            const notFound = (): Response =>
                ({
                    ok: false,
                    status: 404,
                    json: async () => ({}),
                    text: async () => 'not found',
                }) as unknown as Response
            globalThis.fetch = async (url: RequestInfo | URL, options: RequestInit = {}): Promise<Response> => {
                const method = options.method ?? 'GET'
                if (method === 'GET') {
                    const page = Number(new URL(String(url)).searchParams.get('page') ?? '1')
                    const snapshot = comments.map(({ id, body, author }) => ({ id, body, user: { login: author } }))
                    fireOnce(afterNextRead)
                    return json(page === 1 ? snapshot : [])
                }
                if (method === 'POST') {
                    comments.push({
                        id: ++nextId,
                        body: JSON.parse(String(options.body)).body,
                        author: 'github-actions[bot]',
                    })
                    fireOnce(afterNextWrite)
                    return json(comments.at(-1))
                }
                const id = Number(String(url).split('/').pop())
                if (method === 'PATCH') {
                    const target = comments.find((c) => c.id === id)
                    if (!target) {
                        return notFound()
                    }
                    state.patches += 1
                    target.body = JSON.parse(String(options.body)).body
                    fireOnce(afterNextWrite)
                    return json({})
                }
                if (method === 'DELETE') {
                    if (state.denyDeletes) {
                        return {
                            ok: false,
                            status: 403,
                            json: async () => ({}),
                            text: async () => 'forbidden',
                        } as unknown as Response
                    }
                    const index = comments.findIndex((c) => c.id === id)
                    if (index === -1) {
                        return notFound()
                    }
                    comments.splice(index, 1)
                    return {
                        ok: true,
                        status: 204,
                        json: async () => null,
                        text: async () => '',
                    } as unknown as Response
                }
                return notFound()
            }
            return { comments, afterNextWrite, afterNextRead, state }
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
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
            ])
            const clobber = renderComment(
                build([
                    { id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' },
                    { id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' },
                ])
            )
            github.afterNextWrite.fn = () => {
                github.comments[0].body = clobber
            }
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body) as SectionState
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph', 'dist-size'])
            expect(get(sections, 'eager-graph').inner).toBe('EAGER')
        })

        it('merges duplicate report comments into the oldest and deletes the rest', async () => {
            const github = fakeGitHub([
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
                { body: renderComment(build([{ id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' }])) },
            ])
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body)
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph', 'dist-size'])
        })

        it('never adopts, merges, or deletes a human comment that carries the marker', async () => {
            // Anyone can comment on a public-repo PR: a "Quote reply" of the report keeps
            // the marker inside `> ` prefixes, and a pasted report body is a full match.
            // Neither belongs to the bot — adopting one launders content under the bot's
            // identity, and healing one DELETES a human's comment permanently.
            const quoted = `> ${MARKER}\n> ## 🤖 CI report\n\nwow, look at this bundle jump`
            const pasted = renderComment(
                build([{ id: 'bundle-size', status: 'fail', summary: 'forged', body: 'FORGED' }])
            )
            const github = fakeGitHub([
                { body: quoted, author: 'some-human' },
                { body: pasted, author: 'some-human' },
            ])
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(3)
            expect(github.comments[0]).toMatchObject({ body: quoted, author: 'some-human' })
            expect(github.comments[1]).toMatchObject({ body: pasted, author: 'some-human' })
            const bot = github.comments[2]
            expect(bot.author).toBe('github-actions[bot]')
            expect([...parseSections(bot.body).keys()]).toEqual(['eager-graph'])
        })

        it('retries the write when the primary comment is deleted underneath it', async () => {
            // A concurrent healer can delete the comment between our read and our PATCH.
            // The 404 must re-enter the retry loop, not take the give-up path — otherwise
            // the section is silently lost for the whole run.
            const github = fakeGitHub([
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
            ])
            github.afterNextRead.fn = () => {
                github.comments.splice(0)
            }
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            expect([...parseSections(github.comments[0].body).keys()]).toEqual(['eager-graph'])
        })

        it('swallows a duplicate that another healer already deleted', async () => {
            // Two workflows can heal the same duplicate concurrently; the loser's DELETE
            // 404s. That is success (the duplicate is gone), not a reason to abort.
            const github = fakeGitHub([
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
                { body: renderComment(build([{ id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' }])) },
            ])
            const duplicateId = github.comments[1].id
            github.afterNextRead.fn = () => {
                github.comments.splice(
                    github.comments.findIndex((c) => c.id === duplicateId),
                    1
                )
            }
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(1)
            const sections = parseSections(github.comments[0].body)
            expect([...sections.keys()]).toEqual(['bundle-size', 'eager-graph', 'dist-size'])
        })

        it('succeeds without burning retries when a duplicate cannot be deleted', async () => {
            // Healing is best-effort: the section landed in the primary, which is what
            // success means. Requiring the duplicate count to reach one would re-PATCH
            // identical content on every attempt and log a lying give-up.
            const github = fakeGitHub([
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
                { body: renderComment(build([{ id: 'dist-size', status: 'info', summary: 'd', body: 'DIST' }])) },
            ])
            github.state.denyDeletes = true
            await postSection({ id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' }, opts)
            expect(github.comments).toHaveLength(2)
            expect([...parseSections(github.comments[0].body).keys()]).toEqual([
                'bundle-size',
                'eager-graph',
                'dist-size',
            ])
            expect(github.state.patches).toBe(1)
        })

        it('gives up cleanly when a concurrent writer keeps clobbering', async () => {
            // The comment is a nicety — exhausting maxAttempts must warn and resolve,
            // never throw, or a comment race reddens the whole job.
            const github = fakeGitHub([
                { body: renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }])) },
            ])
            const clobber = renderComment(build([{ id: 'bundle-size', status: 'ok', summary: 'b', body: 'BUNDLE' }]))
            const persist = (): void => {
                github.comments[0].body = clobber
                github.afterNextWrite.fn = persist
            }
            github.afterNextWrite.fn = persist
            await expect(
                postSection(
                    { id: 'eager-graph', status: 'warn', summary: 'e', body: 'EAGER' },
                    { ...opts, maxAttempts: 2 }
                )
            ).resolves.toBeUndefined()
            expect([...parseSections(github.comments[0].body).keys()]).toEqual(['bundle-size'])
        })
    })
})
