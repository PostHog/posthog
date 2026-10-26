import { SandboxToolNameEnumApi } from '../../generated/api.schemas'
import { describeSearch } from './playgroundDisplay'

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
