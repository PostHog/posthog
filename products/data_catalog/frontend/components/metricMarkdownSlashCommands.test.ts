import { Editor } from '@tiptap/core'

import { METRIC_MARKDOWN_EXTENSIONS, metricMarkdownConverter } from './metricMarkdown'
import { createMetricMarkdownSlashCommands, insertCatalogReference } from './metricMarkdownSlashCommands'

function buildEditor(): Editor {
    return new Editor({
        extensions: METRIC_MARKDOWN_EXTENSIONS,
        content: metricMarkdownConverter.markdownToDoc(''),
    })
}

describe('metricMarkdownSlashCommands', () => {
    it('the SQL block command serializes to a sql fence', () => {
        const editor = buildEditor()
        const sqlItem = createMetricMarkdownSlashCommands({ current: null }).find((item) => item.title === 'SQL block')
        expect(sqlItem).not.toBeUndefined()

        sqlItem?.command(editor)
        editor.commands.insertContent('SELECT count() FROM events')

        const markdown = metricMarkdownConverter.docToMarkdown(editor.getJSON())
        expect(markdown).toContain('```sql')
        expect(markdown).toContain('SELECT count() FROM events')
        editor.destroy()
    })

    it('an inserted catalog reference reads as inline code and round-trips', () => {
        const editor = buildEditor()
        insertCatalogReference(editor, 'monthly_active_users')

        const markdown = metricMarkdownConverter.docToMarkdown(editor.getJSON())
        expect(markdown).toContain('`monthly_active_users`')
        expect(metricMarkdownConverter.isRoundTripSafe(markdown)).toBe(true)
        editor.destroy()
    })
})
