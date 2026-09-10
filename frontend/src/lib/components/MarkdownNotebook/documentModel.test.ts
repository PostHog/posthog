import { getMarkdownNotebookVisualGroups, rekeyNotebookNodes } from './documentModel'
import { parseMarkdownNotebook } from './markdown'
import { NotebookBlockNode } from './types'

describe('documentModel', () => {
    describe('getMarkdownNotebookVisualGroups', () => {
        it('keeps a table written between paragraphs inside the surrounding text group', () => {
            const document = parseMarkdownNotebook(
                [
                    'Signup completion improved after the onboarding changes.',
                    '',
                    '| Step | Completion |',
                    '| --- | ---: |',
                    '| Signup form | 82% |',
                    '',
                    'Workspace setup is the step to watch next.',
                ].join('\n')
            )

            const groups = getMarkdownNotebookVisualGroups(document.nodes)

            expect(groups).toHaveLength(1)
            expect(groups[0].type === 'text' ? groups[0].items.map((item) => item.node.type) : []).toEqual([
                'paragraph',
                'table',
                'paragraph',
            ])
        })

        it('keeps a table inserted as its own node standing alone', () => {
            const document = parseMarkdownNotebook(
                [
                    'Signup completion improved after the onboarding changes.',
                    '',
                    '',
                    '| Step | Completion |',
                    '| --- | ---: |',
                ].join('\n')
            )

            const groups = getMarkdownNotebookVisualGroups(document.nodes)

            expect(groups.map((group) => group.type)).toEqual(['text', 'block'])
        })
    })

    describe('rekeyNotebookNodes', () => {
        it('gives a pasted component node a fresh nodeId so it no longer shares logic with the original', () => {
            // A trend chart carrying a persisted nodeId, as it exists once saved and copied.
            const copied: NotebookBlockNode = {
                type: 'component',
                tagName: 'Query',
                id: 'original-block',
                props: {
                    nodeId: 'shared-node-id',
                    query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } },
                },
            } as NotebookBlockNode

            const [pasted] = rekeyNotebookNodes([copied], 'paste-seed')

            expect(pasted.id).not.toBe('original-block')
            // The nodeId prop keys the node's logic; a shared value is what let edits leak between copies.
            expect((pasted as any).props.nodeId).not.toBe('shared-node-id')
            expect((pasted as any).props.nodeId).toBe(pasted.id)
            // The rest of the node is preserved.
            expect((pasted as any).props.query).toEqual((copied as any).props.query)
        })

        it('leaves a component node without a persisted nodeId untouched beyond the block id', () => {
            const copied: NotebookBlockNode = {
                type: 'component',
                tagName: 'Query',
                id: 'original-block',
                props: { query: { kind: 'InsightVizNode', source: { kind: 'TrendsQuery', series: [] } } },
            } as NotebookBlockNode

            const [pasted] = rekeyNotebookNodes([copied], 'paste-seed')

            expect(pasted.id).not.toBe('original-block')
            expect((pasted as any).props.nodeId).toBeUndefined()
        })
    })
})
