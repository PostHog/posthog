import { Locator, Page, expect } from '@playwright/test'

export class FunnelsInsight {
    readonly chart: Locator
    readonly stepBars: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('funnel-bar-vertical').or(page.getByTestId('funnel-bar-horizontal'))
        this.stepBars = page.getByTestId('funnel-bar-vertical').locator('.StepLegend')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart.first()).toBeVisible()
    }
}
