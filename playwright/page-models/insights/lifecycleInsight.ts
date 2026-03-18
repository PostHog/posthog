import { Locator, Page, expect } from '@playwright/test'

export class LifecycleInsight {
    readonly chart: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('trend-line-graph')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}
