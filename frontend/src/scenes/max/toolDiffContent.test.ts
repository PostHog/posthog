import { Language } from 'lib/components/CodeSnippet/CodeSnippet'

import { findAllDiffContent, findDiffContent, getDiffStats, languageFromPath } from './toolDiffContent'

const flatDiff = { type: 'diff', path: 'a.ts', oldText: 'old', newText: 'new' }
const nestedDiff = { type: 'content', content: { type: 'diff', path: 'b.py', oldText: null, newText: 'print(1)' } }
const textBlock = { type: 'text', text: 'hello' }

describe('toolDiffContent', () => {
    describe('findDiffContent', () => {
        it.each([
            ['flat diff block', [textBlock, flatDiff], { path: 'a.ts', oldText: 'old', newText: 'new' }],
            ['ACP-nested diff block', [textBlock, nestedDiff], { path: 'b.py', oldText: null, newText: 'print(1)' }],
        ])('extracts the first %s', (_label, content, expected) => {
            expect(findDiffContent(content)).toEqual({ type: 'diff', ...expected })
        })

        it.each([
            ['no diff blocks', [textBlock, { type: 'content', content: textBlock }]],
            ['empty content', []],
            ['non-object members', [null, undefined, 'string', 42]],
        ])('returns null for %s', (_label, content) => {
            expect(findDiffContent(content as unknown[])).toBeNull()
        })
    })

    describe('findAllDiffContent', () => {
        it('collects every diff block (flat + nested), in order — MultiEdit emits one per edit', () => {
            const second = { type: 'diff', path: 'a.ts', oldText: 'b', newText: 'c' }
            expect(findAllDiffContent([flatDiff, textBlock, nestedDiff, second])).toEqual([
                { type: 'diff', path: 'a.ts', oldText: 'old', newText: 'new' },
                { type: 'diff', path: 'b.py', oldText: null, newText: 'print(1)' },
                { type: 'diff', path: 'a.ts', oldText: 'b', newText: 'c' },
            ])
        })

        it('returns an empty array when there are no diff blocks', () => {
            expect(findAllDiffContent([textBlock])).toEqual([])
        })
    })

    describe('getDiffStats', () => {
        it.each([
            ['pure addition', 'a\nb', 'a\nb\nc', { added: 1, removed: 0 }],
            ['pure removal', 'a\nb\nc', 'a\nb', { added: 0, removed: 1 }],
            ['changed line', 'a\nb\nc', 'a\nB\nc', { added: 1, removed: 1 }],
            ['new file (null old)', null, 'a\nb\nc', { added: 3, removed: 0 }],
            ['new file (empty old)', '', 'a\nb', { added: 2, removed: 0 }],
            ['no change', 'a\nb', 'a\nb', { added: 0, removed: 0 }],
        ])('counts %s', (_label, oldText, newText, expected) => {
            expect(getDiffStats(oldText, newText)).toEqual(expected)
        })
    })

    describe('languageFromPath', () => {
        it.each([
            ['foo.ts', Language.TypeScript],
            ['foo.tsx', Language.TypeScript],
            ['foo.py', Language.Python],
            ['foo.js', Language.JavaScript],
            ['foo.jsx', Language.JavaScript],
            ['foo.json', Language.JSON],
            ['foo.sql', Language.SQL],
            ['foo.go', Language.Go],
            ['foo.yaml', Language.YAML],
            ['foo.yml', Language.YAML],
            ['foo.sh', Language.Bash],
            ['foo.rb', Language.Ruby],
            ['nested/dir/Component.TSX', Language.TypeScript],
            ['Dockerfile', Language.Text],
            ['foo.unknownext', Language.Text],
            [undefined, Language.Text],
        ])('maps %s to the expected language', (path, expected) => {
            expect(languageFromPath(path)).toBe(expected)
        })
    })
})
