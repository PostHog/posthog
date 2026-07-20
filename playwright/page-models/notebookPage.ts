import { Locator, Page, expect } from '@playwright/test'

export class NotebookPage {
    readonly page: Page

    readonly newNotebookButton: Locator
    readonly notebooksTable: Locator
    readonly searchInput: Locator
    readonly editor: Locator
    readonly titleHeading: Locator

    constructor(page: Page) {
        this.page = page

        this.newNotebookButton = page.getByTestId('new-notebook')
        this.notebooksTable = page.getByTestId('notebooks-table')
        this.searchInput = page.getByTestId('notebooks-search')
        this.editor = page.locator('[data-markdown-notebook-editor]')
        this.titleHeading = page.locator('.MarkdownNotebook__text-block--title')
    }

    async goToList(): Promise<void> {
        await this.page.goto('/notebooks', { waitUntil: 'domcontentloaded' })
        await expect(this.notebooksTable).toBeVisible({ timeout: 15000 })
    }

    async createNew(name?: string): Promise<void> {
        await this.goToList()
        await this.newNotebookButton.click()
        await expect(this.editor).toBeVisible({ timeout: 10000 })
        await this.page.waitForURL(/\/notebooks\/(?!new)/, { timeout: 15000 })

        if (name) {
            await this.editTitle(name)
        }
    }

    async editTitle(name: string): Promise<void> {
        const savePromise = this.waitForSave()
        await this.titleHeading.click()
        await this.page.keyboard.press('ControlOrMeta+a')
        await this.page.keyboard.type(name)
        await expect(this.page).toHaveTitle(new RegExp(name), { timeout: 10000 })
        await savePromise
    }

    /**
     * Markdown notebooks save through the realtime endpoint
     * (POST .../collab/markdown_save), not a plain PATCH.
     */
    async waitForSave(): Promise<void> {
        await this.page.waitForResponse(
            (response) =>
                response.url().includes('/notebooks/') &&
                response.url().includes('/collab/markdown_save') &&
                response.request().method() === 'POST' &&
                response.status() === 200,
            { timeout: 15000 }
        )
    }

    /** Place the caret in a fresh empty paragraph at the end of the notebook. */
    async focusNewParagraphAtEnd(): Promise<void> {
        // Click a text block directly: clicking the canvas itself can land on hover
        // affordances (add-block boundaries) instead of placing the caret.
        await this.page.locator('.MarkdownNotebook__text-block').last().click()
        await this.page.keyboard.press('End')
        await this.page.keyboard.press('Enter')
    }

    async addInsightViaSlashCommand(
        type: 'Trend' | 'Funnel' | 'Retention' | 'Paths' | 'Stickiness' | 'Lifecycle' | 'SQL'
    ): Promise<void> {
        const currentCount = await this.insightNodes.count()
        const savePromise = this.waitForSave()
        await this.focusNewParagraphAtEnd()
        await this.page.keyboard.type('/')
        await expect(this.page.locator('.MarkdownNotebook__insert-menu')).toBeVisible()
        await this.page.keyboard.type(type)
        const menuItem = this.page.getByRole('option', { name: type, exact: true })
        await expect(menuItem).toBeVisible()
        await menuItem.click()
        await expect(this.insightNodes).toHaveCount(currentCount + 1, { timeout: 15000 })
        await savePromise
    }

    get insightNodes(): Locator {
        return this.page.getByTestId('notebook-node-query')
    }

    get componentShells(): Locator {
        return this.page.locator('.MarkdownNotebook__component-shell')
    }

    /** Open the block's filters/settings panel via its toolbar. */
    async expandInsightNode(index: number = 0): Promise<void> {
        const shell = this.componentShells.nth(index)
        await shell.hover()
        await shell.getByLabel('Show filters').click()
    }

    async waitForInsightLoad(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
    }

    /**
     * Select a chart type from the chart filter dropdown.
     * Notebook-specific: avoids strict mode violations from dual insight elements.
     */
    async selectChartType(namePattern: RegExp): Promise<void> {
        await this.page.keyboard.press('Escape')
        await this.page.getByTestId('chart-filter').click()
        await this.page.getByRole('menuitem', { name: namePattern }).click()
        await this.waitForInsightLoad()
    }

    /**
     * Select a date range from the date filter dropdown.
     * Notebook-specific: avoids strict mode violations from dual insight elements.
     */
    async selectDateRange(text: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        const dataAttr = `date-filter-${text.toLowerCase().replace(/\s+/g, '-')}`
        await this.page.getByTestId('date-filter').click()
        await this.page.getByTestId(dataAttr).click()
        await this.waitForInsightLoad()
    }

    async removeInsightNode(index: number = 0): Promise<void> {
        const shell = this.componentShells.nth(index)
        await shell.hover()
        await shell.getByLabel('Delete component').click()
    }

    async deleteFromList(notebookName: string): Promise<void> {
        const row = this.notebooksTable.getByRole('row').filter({ hasText: notebookName })
        await row.getByLabel('more').click()
        await this.page.getByRole('menuitem', { name: 'Delete' }).click()
    }

    getNotebookRowByName(name: string): Locator {
        return this.notebooksTable.getByRole('row').filter({ hasText: name })
    }
}
