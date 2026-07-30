import { parseMarkdownNotebook, serializeMarkdownNotebook } from 'lib/components/MarkdownNotebook/markdown'

import { NOTEBOOK_MARKDOWN_REGISTRY } from '../Notebook/markdownNotebookRegistry'
import { NOTEBOOK_TEMPLATES } from './notebookTemplates'

describe('notebookTemplates', () => {
    it.each(NOTEBOOK_TEMPLATES.map((template) => [template.short_id, template] as const))(
        '%s parses into known components and round-trips unchanged',
        (_shortId, template) => {
            const document = parseMarkdownNotebook(template.markdown)

            expect(document.errors).toEqual([])

            const unknownTags = document.nodes
                .filter((node) => node.type === 'component')
                .map((node) => node.tagName)
                .filter((tagName) => !(tagName in NOTEBOOK_MARKDOWN_REGISTRY.components))
            expect(unknownTags).toEqual([])

            expect(serializeMarkdownNotebook(document)).toEqual(template.markdown)
        }
    )

    it('has a unique short_id per template', () => {
        const shortIds = NOTEBOOK_TEMPLATES.map((template) => template.short_id)

        expect(new Set(shortIds).size).toEqual(shortIds.length)
    })
})
