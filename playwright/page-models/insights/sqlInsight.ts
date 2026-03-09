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
        // Use Control+A (not Meta+A) because Meta maps to Super on Linux CI
        await this.page.keyboard.press('Control+A')
        await this.page.keyboard.type(query)
        // Dismiss any autocomplete popup that may have been triggered.
        // Monaco's HogQL autocomplete fires on space/comma/period/{ characters,
        // and the suggestion widget can intercept the next keystroke (e.g. the
        // Run button click) if left open.
        await this.page.keyboard.press('Escape')
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
