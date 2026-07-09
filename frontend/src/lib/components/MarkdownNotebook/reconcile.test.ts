import { parseMarkdownNotebook } from './markdown'
import { reconcileNotebookDocuments } from './reconcile'
import { NotebookComponentBlockNode, NotebookListBlockNode } from './types'

describe('reconcileNotebookDocuments', () => {
    it('preserves node identity for unchanged blocks at the same index', () => {
        const previousDocument = parseMarkdownNotebook('Alpha\n\nBeta')
        const nextDocument = parseMarkdownNotebook('Alpha\n\nBeta')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)

        expect(result.document.nodes.map((node) => node.id)).toEqual(previousDocument.nodes.map((node) => node.id))
        expect(result.changes).toEqual([])
    })

    it('preserves node identity for moved blocks through exact fingerprints', () => {
        const previousDocument = parseMarkdownNotebook('Alpha\n\nBeta')
        const nextDocument = parseMarkdownNotebook('Beta\n\nAlpha')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)

        expect(result.document.nodes.map((node) => node.id)).toEqual([
            previousDocument.nodes[1].id,
            previousDocument.nodes[0].id,
        ])
        expect(result.changes.map((change) => change.type).sort()).toEqual(['moved', 'moved'])
    })

    it('preserves node identity for edited blocks through text similarity', () => {
        const previousDocument = parseMarkdownNotebook('Activation improved today')
        const nextDocument = parseMarkdownNotebook('Activation improved today after launch')

        expect(nextDocument.nodes[0].id).not.toEqual(previousDocument.nodes[0].id)

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)

        expect(result.document.nodes[0].id).toEqual(previousDocument.nodes[0].id)
        expect(result.changes).toEqual([{ type: 'updated', nodeId: previousDocument.nodes[0].id, index: 0 }])
    })

    it('does not reuse identity for dissimilar replacement text', () => {
        const previousDocument = parseMarkdownNotebook('Activation improved today')
        const nextDocument = parseMarkdownNotebook('Completely unrelated content about something else')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)

        expect(result.document.nodes[0].id).not.toEqual(previousDocument.nodes[0].id)
        expect(result.changes.map((change) => change.type).sort()).toEqual(['deleted', 'inserted'])
    })

    it('preserves component identity through the id prop when other props change', () => {
        const previousDocument = parseMarkdownNotebook('<SummaryCard id="summary-1" title="Before" />')
        const nextDocument = parseMarkdownNotebook(
            '<SummaryCard id="summary-1" title="After summary" summary="Done" />'
        )

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)
        const component = result.document.nodes[0] as NotebookComponentBlockNode

        expect(component.id).toEqual(previousDocument.nodes[0].id)
        expect(result.changes).toEqual([{ type: 'updated', nodeId: previousDocument.nodes[0].id, index: 0 }])
    })

    it('reports insertions without disturbing surrounding identity', () => {
        const previousDocument = parseMarkdownNotebook('Alpha\n\nOmega')
        const nextDocument = parseMarkdownNotebook('Alpha\n\nInserted in the middle\n\nOmega')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)

        expect(result.document.nodes[0].id).toEqual(previousDocument.nodes[0].id)
        expect(result.document.nodes[2].id).toEqual(previousDocument.nodes[1].id)
        expect(result.changes).toEqual([
            { type: 'inserted', nodeId: result.document.nodes[1].id, index: 1 },
            { type: 'moved', nodeId: previousDocument.nodes[1].id, previousIndex: 1, index: 2 },
        ])
    })

    it('preserves list item identity through positional fallback when one item is edited', () => {
        const previousDocument = parseMarkdownNotebook('- One\n- Two\n- Three')
        const nextDocument = parseMarkdownNotebook('- One edited\n- Two\n- Three')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)
        const previousList = previousDocument.nodes[0] as NotebookListBlockNode
        const nextList = result.document.nodes[0] as NotebookListBlockNode

        expect(nextList.id).toEqual(previousList.id)
        expect(nextList.items.map((item) => item.id)).toEqual(previousList.items.map((item) => item.id))
    })

    it('keeps list item identity stable when items move within the list', () => {
        const previousDocument = parseMarkdownNotebook('- One\n- Two\n- Three')
        const nextDocument = parseMarkdownNotebook('- Two\n- Three\n- One')

        const result = reconcileNotebookDocuments(previousDocument, nextDocument)
        const previousList = previousDocument.nodes[0] as NotebookListBlockNode
        const nextList = result.document.nodes[0] as NotebookListBlockNode

        expect(nextList.items.map((item) => item.id)).toEqual([
            previousList.items[1].id,
            previousList.items[2].id,
            previousList.items[0].id,
        ])
    })
})
