import { markdownCrc, mergeNotebookMarkdownChanges, tryApplyTextChanges } from './collaboration'

describe('mergeNotebookMarkdownChanges', () => {
    it('returns the local markdown when the remote matches the base', () => {
        const baseMarkdown = '# Title\n\nShared paragraph'
        const localMarkdown = '# Title\n\nShared paragraph with local edits'

        const result = mergeNotebookMarkdownChanges({
            baseMarkdown,
            localMarkdown,
            remoteMarkdown: baseMarkdown,
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual(localMarkdown)
    })

    it('returns the remote markdown when the local matches the base', () => {
        const baseMarkdown = '# Title\n\nShared paragraph'
        const remoteMarkdown = '# Title\n\nShared paragraph with remote edits'

        const result = mergeNotebookMarkdownChanges({
            baseMarkdown,
            localMarkdown: baseMarkdown,
            remoteMarkdown,
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual(remoteMarkdown)
    })

    it('includes blocks inserted only on the remote side', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\nFirst',
            localMarkdown: '# Title\n\nFirst',
            remoteMarkdown: '# Title\n\nFirst\n\nRemote addition',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title\n\nFirst\n\nRemote addition')
    })

    it('keeps blocks inserted only locally next to their anchors', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\nFirst\n\nLast',
            localMarkdown: '# Title\n\nFirst\n\nLocal insert\n\nLast',
            remoteMarkdown: '# Title\n\nFirst\n\nLast\n\nRemote tail',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title\n\nFirst\n\nLocal insert\n\nLast\n\nRemote tail')
    })

    it('merges non-overlapping edits to the same block at the text level', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: 'Activation improved today.',
            localMarkdown: 'Activation improved today after launch.',
            remoteMarkdown: 'Activation clearly improved today.',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('Activation clearly improved today after launch.')
    })

    it('keeps the local version and reports a conflict for overlapping edits', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: 'Activation improved today.',
            localMarkdown: 'Activation improved locally.',
            remoteMarkdown: 'Activation improved remotely.',
        })

        expect(result.conflicts).toHaveLength(1)
        expect(result.conflicts[0].reason).toEqual('Local and remote edited the same block')
        expect(result.conflicts[0].localMarkdown).toEqual('Activation improved locally.')
        expect(result.conflicts[0].remoteMarkdown).toEqual('Activation improved remotely.')
        expect(result.mergedMarkdown).toEqual('Activation improved locally.')
    })

    it('reports a conflict when the remote edits a block that was deleted locally', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\nDoomed paragraph',
            localMarkdown: '# Title',
            remoteMarkdown: '# Title\n\nDoomed paragraph edited remotely',
        })

        expect(result.conflicts).toHaveLength(1)
        expect(result.conflicts[0].reason).toEqual('Remote changed a block that was deleted locally')
        expect(result.mergedMarkdown).toEqual('# Title')
    })

    it('lets a remote deletion win over an unchanged local block', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\nRemoved remotely',
            localMarkdown: '# Title\n\nRemoved remotely',
            remoteMarkdown: '# Title',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title')
    })

    it('lets a remote deletion win over a local edit but reports a conflict', () => {
        // The deletion wins (re-adding would resurrect deleted blocks on every merge), but the
        // local user must be told their edit was discarded.
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\nEdited locally',
            localMarkdown: '# Title\n\nEdited locally with changes',
            remoteMarkdown: '# Title',
        })

        expect(result.conflicts).toHaveLength(1)
        expect(result.conflicts[0].reason).toEqual('Remote deleted a block that was edited locally')
        expect(result.conflicts[0].localMarkdown).toEqual('Edited locally with changes')
        expect(result.conflicts[0].remoteMarkdown).toEqual('')
        expect(result.mergedMarkdown).toEqual('# Title')
    })

    it('merges edits in different list items of the same list', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '- First\n- Second',
            localMarkdown: '- First locally\n- Second',
            remoteMarkdown: '- First\n- Second remotely',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('- First locally\n- Second remotely')
    })

    it('keeps component blocks intact when only one side changes their props', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\n<Chat id="chat-1" />',
            localMarkdown: '# Title\n\n<Chat id="chat-1" title="Named" />',
            remoteMarkdown: '# Title\n\n<Chat id="chat-1" />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title\n\n<Chat id="chat-1" title="Named" />')
    })
})

describe('collaboration text utilities', () => {
    describe('tryApplyTextChanges', () => {
        it('applies ascending non-overlapping changes', () => {
            expect(
                tryApplyTextChanges('abcdef', [
                    { start: 0, end: 1, text: 'X' },
                    { start: 3, end: 5, text: 'Y' },
                ])
            ).toEqual('XbcYf')
        })

        it('applies an insertion into an empty string', () => {
            expect(tryApplyTextChanges('', [{ start: 0, end: 0, text: 'hello' }])).toEqual('hello')
        })

        it('treats offsets as UTF-16 code units', () => {
            // 🦔 is two code units, so the trailing char sits at offset 2
            expect(tryApplyTextChanges('🦔a', [{ start: 2, end: 3, text: 'b' }])).toEqual('🦔b')
        })

        it.each([
            ['end beyond base', 'abc', [{ start: 0, end: 4, text: 'x' }]],
            ['start after end', 'abc', [{ start: 2, end: 1, text: 'x' }]],
            [
                'overlapping changes',
                'abcdef',
                [
                    { start: 0, end: 3, text: 'x' },
                    { start: 2, end: 4, text: 'y' },
                ],
            ],
            ['non-numeric offsets', 'abc', [{ start: '0' as unknown as number, end: 1, text: 'x' }]],
            ['fractional offsets', 'abc', [{ start: 0.5, end: 1, text: 'x' }]],
            ['missing text', 'abc', [{ start: 0, end: 1 } as unknown as { start: number; end: number; text: string }]],
        ])('rejects invalid changes: %s', (_name, base, changes) => {
            expect(tryApplyTextChanges(base as string, changes as any)).toBeNull()
        })
    })

    describe('markdownCrc', () => {
        // Shared vectors with test_collab.py — both sides hash UTF-16-LE bytes (zlib.crc32 parity)
        it.each([
            ['', 0],
            ['hello', 1427272415],
            ['# Title\n\nSome text 🦔', 2055511376],
            ['naïve café ✨', 591606638],
        ])('matches the backend CRC for %j', (text, expected) => {
            expect(markdownCrc(text as string)).toEqual(expected)
        })
    })
})
