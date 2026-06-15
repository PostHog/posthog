import { describe, expect, it } from 'vitest'

import {
    MAX_DESCRIPTION_LEN,
    parseMemoryDoc,
    parseMemoryFrontmatter,
    serializeMemoryDoc,
    validateForWrite,
} from './format'

describe('memory format', () => {
    describe('parse + serialize round-trip', () => {
        it('round-trips a basic doc', () => {
            const raw = serializeMemoryDoc({
                description: 'Postgres pool exhausted during traffic spike.',
                tags: ['incident', 'db'],
                content: '## Symptoms\nAPI 5xx for 10 minutes.',
                createdAt: '2026-02-14T03:22:10Z',
                updatedAt: '2026-02-14T03:22:10Z',
            })
            const parsed = parseMemoryDoc(raw)
            expect(parsed.description).toBe('Postgres pool exhausted during traffic spike.')
            expect(parsed.tags).toEqual(['incident', 'db'])
            expect(parsed.createdAt).toBe('2026-02-14T03:22:10Z')
            expect(parsed.content).toBe('## Symptoms\nAPI 5xx for 10 minutes.')
        })

        it('preserves embedded `---` inside the body', () => {
            // The body has its own --- separators — only the FIRST leading
            // frontmatter block is treated as YAML. Anything after is body.
            const raw = serializeMemoryDoc({
                description: 'Doc with body separators',
                tags: [],
                content: 'one\n\n---\n\ntwo\n\n---\n\nthree',
            })
            const parsed = parseMemoryDoc(raw)
            expect(parsed.content).toBe('one\n\n---\n\ntwo\n\n---\n\nthree')
        })

        it('handles a description containing a colon (quoting)', () => {
            const raw = serializeMemoryDoc({
                description: 'Incident: db pool was empty at 03:22.',
                tags: [],
                content: 'body',
            })
            const parsed = parseMemoryDoc(raw)
            expect(parsed.description).toBe('Incident: db pool was empty at 03:22.')
        })

        it('handles a description containing double quotes', () => {
            const raw = serializeMemoryDoc({
                description: 'User said "this is broken"',
                tags: [],
                content: 'body',
            })
            const parsed = parseMemoryDoc(raw)
            expect(parsed.description).toBe('User said "this is broken"')
        })
    })

    describe('parse edge cases', () => {
        it('parses a doc with no frontmatter as content-only', () => {
            const parsed = parseMemoryDoc('just a body, no fence')
            expect(parsed.description).toBe('')
            expect(parsed.tags).toEqual([])
            expect(parsed.content).toBe('just a body, no fence')
        })

        it('returns empty header when frontmatter fence is unterminated', () => {
            // Missing closing ---; the whole thing is body, parser bails.
            const parsed = parseMemoryDoc('---\ndescription: oops\n\nactual body')
            expect(parsed.description).toBe('')
            expect(parsed.content).toBe('---\ndescription: oops\n\nactual body')
        })

        it('drops unknown frontmatter keys silently', () => {
            const raw = '---\ndescription: hi\nunknown_key: ignored\ntags: [a]\n---\nbody'
            const parsed = parseMemoryDoc(raw)
            expect(parsed.description).toBe('hi')
            expect(parsed.tags).toEqual(['a'])
            expect(parsed.content).toBe('body')
        })

        it('parses tags as [] when absent', () => {
            const raw = '---\ndescription: hi\n---\nbody'
            const parsed = parseMemoryDoc(raw)
            expect(parsed.tags).toEqual([])
        })

        it('parseMemoryFrontmatter ignores the body', () => {
            const raw = serializeMemoryDoc({
                description: 'just the header',
                tags: ['t'],
                content: 'enormous body that should not be read',
            })
            const fm = parseMemoryFrontmatter(raw)
            expect(fm.description).toBe('just the header')
            expect(fm.tags).toEqual(['t'])
        })
    })

    describe('validateForWrite', () => {
        it('rejects empty description', () => {
            expect(() => validateForWrite({ description: '' })).toThrow(/required/)
        })

        it('rejects description over the cap', () => {
            const long = 'x'.repeat(MAX_DESCRIPTION_LEN + 1)
            expect(() => validateForWrite({ description: long })).toThrow(/exceeds/)
        })

        it('rejects a multiline description', () => {
            expect(() => validateForWrite({ description: 'line one\nline two' })).toThrow(/single line/)
        })

        it('accepts a valid description and tag list', () => {
            expect(() => validateForWrite({ description: 'ok', tags: ['a-tag', 'tag_2'] })).not.toThrow()
        })

        it('rejects tags with uppercase or invalid chars', () => {
            expect(() => validateForWrite({ description: 'ok', tags: ['Bad'] })).toThrow(/invalid tag/)
            expect(() => validateForWrite({ description: 'ok', tags: ['has space'] })).toThrow(/invalid tag/)
        })
    })
})
