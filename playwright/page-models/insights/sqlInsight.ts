import { Locator, Page, expect } from '@playwright/test'

export class SqlInsight {
    readonly editor: Locator
    readonly runButton: Locator

    constructor(private readonly page: Page) {
        this.editor = page.getByTestId('editor-scene')
        this.runButton = page.getByTestId('sql-editor-run-button')
    }

    async waitForChart(): Promise<void> {
        await expect(this.editor).toBeVisible()
    }

    async writeQuery(query: string): Promise<void> {
        const editorArea = this.page.getByTestId('hogql-query-editor')
        await editorArea.waitFor({ state: 'visible' })
        // CodeEditor lazy-loads monaco, so the container renders before the editor
        // mounts — clicking too early focuses nothing and insertText is lost.
        await editorArea.locator('[data-editor-ready="true"]').first().waitFor({ state: 'visible' })

        // Monaco treats insertText as typed input, so autocomplete and auto-indent can corrupt a
        // large query. Its paste command updates the controlled model while inserting text verbatim.
        await this.page.evaluate((text) => {
            const editor = (window as any).__monacoEditors?.at(-1)
            const model = editor?.getModel()
            if (!editor || !model) {
                throw new Error('Monaco handle missing')
            }
            editor.focus()
            editor.setSelection(model.getFullModelRange())
            editor.trigger('keyboard', 'paste', { text })
        }, query)
        await this.page.keyboard.press('Escape')
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
