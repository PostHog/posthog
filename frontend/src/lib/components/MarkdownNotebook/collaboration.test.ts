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
            baseMarkdown: '# Title\n\n<SummaryCard id="summary-1" />',
            localMarkdown: '# Title\n\n<SummaryCard id="summary-1" title="Named" />',
            remoteMarkdown: '# Title\n\n<SummaryCard id="summary-1" />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title\n\n<SummaryCard id="summary-1" title="Named" />')
    })

    it('merges concurrent edits to different props of the same component', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '<SummaryCard id="summary-1" />',
            localMarkdown: '<SummaryCard id="summary-1" title="Named locally" />',
            remoteMarkdown: '<SummaryCard id="summary-1" summary="Updated summary" />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('title="Named locally"')
        expect(result.mergedMarkdown).toContain('summary="Updated summary"')
    })

    it('merges concurrent non-overlapping edits to the same string prop at the text level', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '<Prompt question="Summarize the funnel" />',
            localMarkdown: '<Prompt question="Summarize the activation funnel" />',
            remoteMarkdown: '<Prompt question="Summarize the funnel by week" />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('<Prompt question="Summarize the activation funnel by week" />')
    })

    it('keeps a continued string prop edit when an earlier save echo returns', () => {
        // The local client extends the summary past what its own previous save echoed back.
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '<SummaryCard id="summary-1" summary="The funnel" />',
            localMarkdown: '<SummaryCard id="summary-1" summary="The funnel improved by 12% this week" />',
            remoteMarkdown: '<SummaryCard id="summary-1" summary="The funnel improved" />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual(
            '<SummaryCard id="summary-1" summary="The funnel improved by 12% this week" />'
        )
    })

    it('keeps the local version and reports a conflict when both sides rewrite the same prop words', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '<Prompt question="Summarize the funnel data" />',
            localMarkdown: '<Prompt question="Summarize the cohort data" />',
            remoteMarkdown: '<Prompt question="Summarize the retention data" />',
        })

        expect(result.conflicts).toHaveLength(1)
        expect(result.mergedMarkdown).toEqual('<Prompt question="Summarize the cohort data" />')
    })

    it('dedupes a freshly inserted component racing its own save echo', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title\n\n<Prompt question="Summarize" />',
            localMarkdown: '# Title\n\n<SummaryCard id="summary-1" summary="The funnel improved" />',
            remoteMarkdown: '# Title\n\n<SummaryCard id="summary-1" />',
        })

        expect((result.mergedMarkdown.match(/<SummaryCard/g) ?? []).length).toEqual(1)
        expect(result.mergedMarkdown).toEqual('# Title\n\n<SummaryCard id="summary-1" summary="The funnel improved" />')
    })

    it('dedupes a new paragraph with a mid-word typo fix racing its own save echo', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title',
            localMarkdown: '# Title\n\nHello world, this is a paragraph',
            remoteMarkdown: '# Title\n\nHelo world, this is a paragraph',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toEqual('# Title\n\nHello world, this is a paragraph')
    })

    it('keeps genuinely different paragraphs inserted at the same spot by two users', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title',
            localMarkdown: '# Title\n\nNotes from the local user',
            remoteMarkdown: '# Title\n\nA completely different remote thought',
        })

        expect(result.mergedMarkdown).toContain('Notes from the local user')
        expect(result.mergedMarkdown).toContain('A completely different remote thought')
    })

    it('keeps concurrently inserted components that are genuinely different', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '# Title',
            localMarkdown: '# Title\n\n<SummaryCard id="local-summary" />',
            remoteMarkdown: '# Title\n\n<SummaryCard id="remote-summary" />',
        })

        expect(result.mergedMarkdown).toContain('local-summary')
        expect(result.mergedMarkdown).toContain('remote-summary')
    })

    it('merges concurrent replies to the same comment thread by reply id', () => {
        const base = '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"}]} />'
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: base,
            localMarkdown:
                '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"},{"id":"r2","author":"Bob","text":"Local reply"}]} />',
            remoteMarkdown:
                '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"},{"id":"r3","author":"Cay","text":"Remote reply"}]} />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('"id":"r1"')
        expect(result.mergedMarkdown).toContain('Local reply')
        expect(result.mergedMarkdown).toContain('Remote reply')
    })

    it('keeps a reply deletion deleted when the other side merely replied', () => {
        const base =
            '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"},{"id":"r2","author":"Bob","text":"Oops"}]} />'
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: base,
            localMarkdown: '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"}]} />',
            remoteMarkdown:
                '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"First"},{"id":"r2","author":"Bob","text":"Oops"},{"id":"r3","author":"Cay","text":"New"}]} />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).not.toContain('Oops')
        expect(result.mergedMarkdown).toContain('New')
    })

    it('takes the edited version of a reply edited on one side only', () => {
        const base = '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Tpyo"}]} />'
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: base,
            localMarkdown: '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Tpyo"}]} />',
            remoteMarkdown: '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Typo"}]} />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('Typo')
        expect(result.mergedMarkdown).not.toContain('Tpyo')
    })

    it('merges replies added concurrently to a thread that was empty in the base', () => {
        const base = '<Comment ref="banana" replies={[]} />'
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: base,
            localMarkdown: '<Comment ref="banana" replies={[{"id":"r1","author":"Ann","text":"Mine"}]} />',
            remoteMarkdown: '<Comment ref="banana" replies={[{"id":"r2","author":"Bob","text":"Theirs"}]} />',
        })

        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('Mine')
        expect(result.mergedMarkdown).toContain('Theirs')
    })

    it('keeps non-string prop edits atomic per prop', () => {
        const result = mergeNotebookMarkdownChanges({
            baseMarkdown: '<Query query={{"kind":"TrendsQuery","interval":"day"}} />',
            localMarkdown: '<Query query={{"kind":"TrendsQuery","interval":"week"}} title="Weekly" />',
            remoteMarkdown: '<Query query={{"kind":"TrendsQuery","interval":"day"}} hideFilters={true} />',
        })

        // The query object changed only locally and the other props only remotely - all merge.
        expect(result.conflicts).toEqual([])
        expect(result.mergedMarkdown).toContain('"interval":"week"')
        expect(result.mergedMarkdown).toContain('title="Weekly"')
        expect(result.mergedMarkdown).toContain('hideFilters')
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
