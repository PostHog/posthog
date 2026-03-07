import { Locator, Page, expect } from '@playwright/test'

export class StickinessInsight {
    readonly chart: Locator
    readonly detailsTable: Locator

    private readonly detailsLoader: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('insights-graph')
        this.detailsTable = page.getByTestId('insights-table-graph')
        this.detailsLoader = page.locator('.LemonTableLoader')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsTable.waitFor({ state: 'visible' })
        await expect(this.detailsLoader).toHaveCount(0)
    }
}
