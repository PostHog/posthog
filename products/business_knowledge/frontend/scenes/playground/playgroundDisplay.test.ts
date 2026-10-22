import { SandboxToolNameEnumApi } from '../../generated/api.schemas'
import { citationRequest, describeSearch, isCitedChunk } from './playgroundDisplay'

describe('describeSearch', () => {
    it('labels repository search and file reads separately from knowledge search', () => {
        expect(
            describeSearch({
                tool: SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesSearch,
                input: JSON.stringify({ query: 'billing' }),
            })
        ).toEqual({ title: 'Searched repositories', subtitle: 'billing' })
        expect(
            describeSearch({
                tool: SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesFileRetrieve,
                input: JSON.stringify({ repo: 'acme/billing', path: 'src/billing.py' }),
            })
        ).toEqual({ title: 'Read file', subtitle: 'acme/billing/src/billing.py' })
        expect(
            describeSearch({
                tool: SandboxToolNameEnumApi.BusinessKnowledgeDocumentWindowRetrieve,
                input: JSON.stringify({ document_id: 'doc' }),
            }).title
        ).toBe('Read document context')
    })
})

describe('citationRequest', () => {
    it.each([
        {
            name: 'a single-exec search keeps every retrieval argument',
            search: {
                tool: SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch,
                input: 'call business-knowledge-documents-search {"query": "refund", "limit": 5, "rerank": true, "library_id": "lib-1"}',
            },
            expected: { kind: 'search', params: { query: 'refund', limit: 5, rerank: true, library_id: 'lib-1' } },
        },
        {
            name: 'a window read targets its document and ordinal',
            search: {
                tool: SandboxToolNameEnumApi.BusinessKnowledgeDocumentWindowRetrieve,
                input: JSON.stringify({ id: 'doc-1', around_ordinal: 3, radius: 2 }),
            },
            expected: { kind: 'window', documentId: 'doc-1', params: { around_ordinal: 3, radius: 2 } },
        },
        {
            name: 'a repository search has no chunks to show',
            search: {
                tool: SandboxToolNameEnumApi.BusinessKnowledgeRepositoriesSearch,
                input: JSON.stringify({ query: 'billing' }),
            },
            expected: null,
        },
        {
            name: 'an unparseable input has no request',
            search: { tool: SandboxToolNameEnumApi.BusinessKnowledgeDocumentsSearch, input: 'not json' },
            expected: null,
        },
    ])('$name', ({ search, expected }) => {
        expect(citationRequest(search)).toEqual(expected)
    })
})

describe('isCitedChunk', () => {
    const chunk = { source_name: 'Help center', document_title: 'Refunds and cancellations' }

    it.each([
        { name: 'a ref naming the source', refs: ['Help center'], expected: true },
        {
            name: 'a ref that adds a section to the title',
            refs: ['Refunds and cancellations, after 30 days'],
            expected: true,
        },
        { name: 'a ref for another source', refs: ['Support plans'], expected: false },
        { name: 'a blank ref', refs: ['  '], expected: false },
    ])('$name', ({ refs, expected }) => {
        expect(isCitedChunk(chunk, refs)).toBe(expected)
    })
})
