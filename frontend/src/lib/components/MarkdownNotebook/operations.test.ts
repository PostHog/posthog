import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import {
    NotebookOperation,
    applyNotebookOperations,
    diffNotebookDocuments,
    rebaseNotebookOperationStack,
    transformNotebookOperationLists,
} from './operations'
import { reconcileNotebookDocuments } from './reconcile'
import { NotebookDocument } from './types'

function parseDocument(markdown: string): NotebookDocument {
    return parseMarkdownNotebook(markdown)
}

/** Parse `nextMarkdown` and reconcile it against `document` so shared blocks keep their ids. */
function evolveDocument(document: NotebookDocument, nextMarkdown: string): NotebookDocument {
    return reconcileNotebookDocuments(document, parseMarkdownNotebook(nextMarkdown)).document
}

describe('notebook operations', () => {
    describe('diff + apply', () => {
        it.each([
            ['text edit', '# Title\n\nHello world', '# Title\n\nHello brave world'],
            ['block insert', '# Title\n\nFirst', '# Title\n\nFirst\n\nSecond'],
            ['block delete', '# Title\n\nFirst\n\nSecond', '# Title\n\nSecond'],
            ['type change', '# Title\n\nplain', '# Title\n\n## plain'],
            ['list edit', '- one\n- two', '- one\n- two\n- three'],
            ['code edit', '```py\nprint(1)\n```', '```py\nprint(2)\n```'],
            ['component props', '<Query query={{"kind":"A"}} />', '<Query query={{"kind":"B"}} />'],
            ['everything at once', '# T\n\na\n\nb\n\nc', '# T\n\nc edited\n\nnew\n\na'],
        ])('round-trips %s', (_name, fromMarkdown, toMarkdown) => {
            const fromDocument = parseDocument(fromMarkdown)
            const toDocument = evolveDocument(fromDocument, toMarkdown)

            const operations = diffNotebookDocuments(fromDocument, toDocument)
            const result = applyNotebookOperations(fromDocument, operations)

            expect(result).not.toBeNull()
            expect(serializeMarkdownNotebook(result!.document)).toEqual(serializeMarkdownNotebook(toDocument))
            expect(result!.document.nodes.map((node) => node.id)).toEqual(toDocument.nodes.map((node) => node.id))
        })

        it('returns no operations for identical documents', () => {
            const document = parseDocument('# Title\n\nHello')
            expect(diffNotebookDocuments(document, document)).toEqual([])
        })

        it('produces inverse operations that revert the change', () => {
            const fromDocument = parseDocument('# Title\n\nalpha\n\nbeta')
            const toDocument = evolveDocument(fromDocument, '# Title\n\nalpha edited\n\nnew block\n\nbeta')

            const operations = diffNotebookDocuments(fromDocument, toDocument)
            const applied = applyNotebookOperations(fromDocument, operations)
            expect(applied).not.toBeNull()

            const reverted = applyNotebookOperations(applied!.document, applied!.inverted)
            expect(reverted).not.toBeNull()
            expect(serializeMarkdownNotebook(reverted!.document)).toEqual(serializeMarkdownNotebook(fromDocument))
            expect(reverted!.document.nodes.map((node) => node.id)).toEqual(fromDocument.nodes.map((node) => node.id))
        })

        it('expresses a reorder as a move that survives inversion', () => {
            const fromDocument = parseDocument('first\n\nsecond\n\nthird')
            const toDocument = evolveDocument(fromDocument, 'second\n\nthird\n\nfirst')

            const operations = diffNotebookDocuments(fromDocument, toDocument)
            expect(operations).toEqual([
                { type: 'move_block', nodeId: fromDocument.nodes[0].id, afterId: fromDocument.nodes[2].id },
            ])

            const applied = applyNotebookOperations(fromDocument, operations)
            const reverted = applyNotebookOperations(applied!.document, applied!.inverted)
            expect(serializeMarkdownNotebook(reverted!.document)).toEqual(serializeMarkdownNotebook(fromDocument))
        })

        it('fails cleanly when an operation no longer fits the document', () => {
            const document = parseDocument('# Title\n\nHello')
            const staleOperation: NotebookOperation = { type: 'delete_block', nodeId: 'gone' }
            expect(applyNotebookOperations(document, [staleOperation])).toBeNull()
        })
    })

    describe('transform + rebase', () => {
        it('keeps operations on different blocks independent', () => {
            const document = parseDocument('# Title\n\nalpha\n\nbeta')
            const local = diffNotebookDocuments(document, evolveDocument(document, '# Title\n\nalpha edited\n\nbeta'))
            const remote = diffNotebookDocuments(document, evolveDocument(document, '# Title\n\nalpha\n\nbeta edited'))

            const pair = transformNotebookOperationLists(local, remote)
            expect(pair).not.toBeNull()

            const viaRemote = applyNotebookOperations(applyNotebookOperations(document, remote)!.document, pair!.a)
            const viaLocal = applyNotebookOperations(applyNotebookOperations(document, local)!.document, pair!.b)
            expect(serializeMarkdownNotebook(viaRemote!.document)).toEqual(
                serializeMarkdownNotebook(viaLocal!.document)
            )
            expect(serializeMarkdownNotebook(viaRemote!.document)).toEqual('# Title\n\nalpha edited\n\nbeta edited')
        })

        it('transforms text edits within the same block', () => {
            const document = parseDocument('one two three')
            const local = diffNotebookDocuments(document, evolveDocument(document, 'one 1 two three'))
            const remote = diffNotebookDocuments(document, evolveDocument(document, 'one two three 3'))

            const pair = transformNotebookOperationLists(local, remote)
            expect(pair).not.toBeNull()

            const merged = applyNotebookOperations(applyNotebookOperations(document, remote)!.document, pair!.a)
            expect(serializeMarkdownNotebook(merged!.document)).toEqual('one 1 two three 3')
        })

        it('reports a conflict when both sides rewrite the same words', () => {
            const document = parseDocument('Activation improved today.')
            const local = diffNotebookDocuments(document, evolveDocument(document, 'Activation improved locally.'))
            const remote = diffNotebookDocuments(document, evolveDocument(document, 'Activation improved remotely.'))

            expect(transformNotebookOperationLists(local, remote)).toBeNull()
        })

        it('rebases an undo stack over a remote insertion so undo reverts only local edits', () => {
            // Local types " world" into a paragraph; the undo entry holds the inverse ops.
            const baseDocument = parseDocument('# Title\n\nHello')
            const editedDocument = evolveDocument(baseDocument, '# Title\n\nHello world')
            const undoEntry = { ops: diffNotebookDocuments(editedDocument, baseDocument) }

            // A collaborator appends a new paragraph, merged into the local document.
            const mergedDocument = evolveDocument(editedDocument, '# Title\n\nHello world\n\nRemote paragraph')
            const remoteOps = diffNotebookDocuments(editedDocument, mergedDocument)

            const rebased = rebaseNotebookOperationStack([undoEntry], remoteOps)
            expect(rebased).toHaveLength(1)

            const undone = applyNotebookOperations(mergedDocument, rebased[0].ops)
            expect(undone).not.toBeNull()
            expect(serializeMarkdownNotebook(undone!.document)).toEqual('# Title\n\nHello\n\nRemote paragraph')
        })

        it('rebases an undo stack over a concurrent remote edit to the same block', () => {
            const baseDocument = parseDocument('# Title\n\nHello')
            const editedDocument = evolveDocument(baseDocument, '# Title\n\nHello world')
            const undoEntry = { ops: diffNotebookDocuments(editedDocument, baseDocument) }

            // The collaborator prepends to the same paragraph.
            const mergedDocument = evolveDocument(editedDocument, '# Title\n\nWell, Hello world')
            const remoteOps = diffNotebookDocuments(editedDocument, mergedDocument)

            const rebased = rebaseNotebookOperationStack([undoEntry], remoteOps)
            expect(rebased).toHaveLength(1)

            const undone = applyNotebookOperations(mergedDocument, rebased[0].ops)
            expect(undone).not.toBeNull()
            expect(serializeMarkdownNotebook(undone!.document)).toEqual('# Title\n\nWell, Hello')
        })

        it('cascades the rebase through deeper history entries', () => {
            // Two undo entries: first " world" was typed, then "!" was appended.
            const stepZero = parseDocument('Hello')
            const stepOne = evolveDocument(stepZero, 'Hello world')
            const stepTwo = evolveDocument(stepOne, 'Hello world!')
            const entries = [
                { ops: diffNotebookDocuments(stepOne, stepZero) },
                { ops: diffNotebookDocuments(stepTwo, stepOne) },
            ]

            const mergedDocument = evolveDocument(stepTwo, 'Hey, Hello world!')
            const remoteOps = diffNotebookDocuments(stepTwo, mergedDocument)

            const rebased = rebaseNotebookOperationStack(entries, remoteOps)
            expect(rebased).toHaveLength(2)

            const afterFirstUndo = applyNotebookOperations(mergedDocument, rebased[1].ops)
            expect(serializeMarkdownNotebook(afterFirstUndo!.document)).toEqual('Hey, Hello world')

            const afterSecondUndo = applyNotebookOperations(afterFirstUndo!.document, rebased[0].ops)
            expect(serializeMarkdownNotebook(afterSecondUndo!.document)).toEqual('Hey, Hello')
        })

        it('drops conflicting entries and everything older, keeping newer ones', () => {
            const stepZero = parseDocument('alpha\n\nbeta')
            const stepOne = evolveDocument(stepZero, 'alpha rewritten\n\nbeta')
            const stepTwo = evolveDocument(stepOne, 'alpha rewritten\n\nbeta edited')
            const entries = [
                { ops: diffNotebookDocuments(stepOne, stepZero) }, // conflicts with the remote rewrite
                { ops: diffNotebookDocuments(stepTwo, stepOne) }, // does not conflict
            ]

            // Remote rewrites the same words of the first block that entry[0] would revert.
            const mergedDocument = evolveDocument(stepTwo, 'alpha rephrased\n\nbeta edited')
            const remoteOps = diffNotebookDocuments(stepTwo, mergedDocument)

            const rebased = rebaseNotebookOperationStack(entries, remoteOps)
            expect(rebased).toHaveLength(1)
            expect(rebased[0].ops).toEqual(entries[1].ops)
        })
    })
})
