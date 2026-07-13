import { escapePath, joinPath, resolveTreeItemHref, splitPath } from './utils'

describe('project tree utils', () => {
    describe('escapePath', () => {
        it('escapes paths as expected', () => {
            expect(escapePath('a/b')).toEqual('a\\/b')
            expect(escapePath('a/b\\')).toEqual('a\\/b\\\\')
            expect(escapePath('a/b/c')).toEqual('a\\/b\\/c')
            expect(escapePath('a\n\t')).toEqual('a\n\t')
            expect(escapePath('a')).toEqual('a')
            expect(escapePath('')).toEqual('')
        })
    })

    describe('splitPath', () => {
        it('splits paths as expected', () => {
            expect(splitPath('a/b')).toEqual(['a', 'b'])
            expect(splitPath('a\\/b/c')).toEqual(['a/b', 'c'])
            expect(splitPath('a\\/b\\\\/c')).toEqual(['a/b\\', 'c'])
            expect(splitPath('a\\/b\\/c')).toEqual(['a/b/c'])
            expect(splitPath('a\n\t/b')).toEqual(['a\n\t', 'b'])
            expect(splitPath('a\\n\\t/b')).toEqual(['a\\n\\t', 'b'])
            expect(splitPath('a\\\\n\\t/b')).toEqual(['a\\n\\t', 'b'])
            expect(splitPath('a')).toEqual(['a'])
            expect(splitPath('')).toEqual([])
        })
    })

    describe('joinPath', () => {
        it('joins paths as expected', () => {
            expect(joinPath(['a', 'b'])).toEqual('a/b')
            expect(joinPath(['a/b', 'c'])).toEqual('a\\/b/c')
            expect(joinPath(['a/b\\', 'c'])).toEqual('a\\/b\\\\/c')
            expect(joinPath(['a/b/c'])).toEqual('a\\/b\\/c')
            expect(joinPath(['a\n\t', 'b'])).toEqual('a\n\t/b')
            expect(joinPath(['a\\n\\t', 'b'])).toEqual('a\\\\n\\\\t/b')
            expect(joinPath(['a'])).toEqual('a')
            expect(joinPath([])).toEqual('')
        })
    })

    describe('resolveTreeItemHref', () => {
        // Guards against a stored relative shortcut href (e.g. "replayvision") resolving against the current
        // URL and landing on a nonexistent nested route — the tree must push an absolute path.
        it.each([
            ['replay-vision', '/replay-vision'],
            ['project/123/home', '/project/123/home'],
            ['/replay-vision', '/replay-vision'],
            ['https://posthog.com/docs', 'https://posthog.com/docs'],
            ['//cdn.example.com/x', '//cdn.example.com/x'],
        ])('normalizes %p to %p', (input, expected) => {
            expect(resolveTreeItemHref(input)).toEqual(expected)
        })

        it('resolves builder functions and normalizes the result', () => {
            expect(resolveTreeItemHref((ref: string) => `insights/${ref}`, 'abc')).toEqual('/insights/abc')
        })

        it('returns undefined for empty or non-string hrefs', () => {
            expect(resolveTreeItemHref(undefined)).toBeUndefined()
            expect(resolveTreeItemHref('')).toBeUndefined()
            expect(resolveTreeItemHref(null)).toBeUndefined()
        })
    })
})
