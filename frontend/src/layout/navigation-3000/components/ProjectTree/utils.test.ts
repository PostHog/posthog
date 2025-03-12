import { escapePath, joinPath, splitPath } from './utils'

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
})
