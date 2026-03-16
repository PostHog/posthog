import { Locator, Page, expect } from '@playwright/test'

export class ChartInsightBase {
    readonly chart: Locator
    readonly tooltip: Locator

    constructor(
        protected readonly page: Page,
        chartLocator: Locator
    ) {
        this.chart = chartLocator
        this.tooltip = page.getByTestId('insight-tooltip')
    }

    async hoverChartAt(xFraction: number = 0.3, yFraction: number = 0.5): Promise<void> {
        const canvas = this.chart.locator('canvas')
        await expect(canvas).toBeVisible()
        await expect(async () => {
            await canvas.scrollIntoViewIfNeeded()
            const box = (await canvas.boundingBox())!
            await this.page.mouse.move(box.x - 5, box.y - 5)
            await this.page.mouse.move(box.x + box.width * xFraction, box.y + box.height * yFraction)
            await expect(this.tooltip).toBeVisible({ timeout: 1000 })
        }).toPass({ timeout: 15000 })
    }

    async hoverAway(): Promise<void> {
        await this.page.mouse.move(0, 0)
    }
}
