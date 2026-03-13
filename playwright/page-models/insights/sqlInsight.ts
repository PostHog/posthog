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
        await editorArea.click()
        await this.page.keyboard.press('Meta+A')
        await this.page.keyboard.type(query)
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
