import { Locator, Page, expect } from '@playwright/test'

export class RetentionInsight {
    readonly chart: Locator
    readonly table: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('trend-line-graph')
        this.table = page.getByTestId('retention-table')
    }

    async waitForChart(): Promise<void> {
        await expect(this.table).toBeVisible()
    }
}
