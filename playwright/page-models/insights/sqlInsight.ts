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
        await editorArea.click()

        // Paste via the clipboard rather than typing. Character-by-character typing lets Monaco
        // autocomplete intercept keystrokes (space is a trigger character), and insertText is
        // treated as typed input, so Monaco re-indents each line and the indentation compounds —
        // a 32KB query arrives as a 3.2MB document of leading whitespace, which quietly ruins any
        // measurement taken against it. A paste is inserted verbatim.
        await this.page.context().grantPermissions(['clipboard-read', 'clipboard-write'])
        await this.page.evaluate(async (text) => await navigator.clipboard.writeText(text), query)
        await this.page.keyboard.press('ControlOrMeta+a')
        await this.page.keyboard.press('ControlOrMeta+v')
        await this.page.keyboard.press('Escape')
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
