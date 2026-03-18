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
        this.editor = page.getByRole('textbox')
        this.titleHeading = page.getByRole('heading', { level: 1 })
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
        const savePromise = this.page.waitForResponse(
            (response) =>
                response.url().includes('/api/projects/') &&
                response.url().includes('/notebooks/') &&
                response.request().method() === 'PATCH' &&
                response.status() === 200,
            { timeout: 15000 }
        )
        await this.editor.fill(name)
        await expect(this.page).toHaveTitle(new RegExp(name), { timeout: 10000 })
        await savePromise
    }

    async waitForSave(): Promise<void> {
        await this.page.waitForResponse(
            (response) =>
                response.url().includes('/api/projects/') &&
                response.url().includes('/notebooks/') &&
                response.request().method() === 'PATCH' &&
                response.status() === 200,
            { timeout: 15000 }
        )
    }

    async addInsightViaSlashCommand(
        type: 'Trend' | 'Funnel' | 'Retention' | 'Paths' | 'Stickiness' | 'Lifecycle' | 'SQL'
    ): Promise<void> {
        const currentCount = await this.insightNodes.count()
        const savePromise = this.page.waitForResponse(
            (response) =>
                response.url().includes('/api/projects/') &&
                response.url().includes('/notebooks/') &&
                response.request().method() === 'PATCH' &&
                response.status() === 200,
            { timeout: 30000 }
        )
        await this.editor.click()
        await this.page.keyboard.press('ControlOrMeta+End')
        await this.page.keyboard.press('Enter')
        await this.page.keyboard.type(`/${type}`)
        await expect(this.page.getByRole('button', { name: type, exact: true })).toBeVisible()
        await this.page.getByRole('button', { name: type, exact: true }).click()
        await expect(this.insightNodes).toHaveCount(currentCount + 1, { timeout: 15000 })
        await savePromise
    }

    get insightNodes(): Locator {
        return this.page.getByTestId('notebook-node-query')
    }

    async expandInsightNode(index: number = 0): Promise<void> {
        const node = this.insightNodes.nth(index)
        await node.hover()
        const editButton = this.page.getByTestId('notebook-node-edit-settings').nth(index)
        await editButton.click()
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

    async removeInsightNode(): Promise<void> {
        const node = this.insightNodes.first()
        await node.click()
        await this.page.keyboard.press('Backspace')
        await this.page.keyboard.press('Backspace')
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
