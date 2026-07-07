import { Locator, Page, expect } from '@playwright/test'

export class ChartInsightBase {
    readonly chart: Locator
    readonly tooltip: Locator
    readonly dateRangeButton: Locator
    readonly chartTypeButton: Locator
    readonly comparisonButton: Locator

    constructor(
        protected readonly page: Page,
        chartLocator: Locator
    ) {
        this.chart = chartLocator
        this.tooltip = page.getByTestId('insight-tooltip')
        this.dateRangeButton = page.getByTestId('date-filter')
        this.chartTypeButton = page.getByTestId('chart-filter')
        this.comparisonButton = page.getByTestId('compare-filter')
    }

    async waitForChart(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.chart).toBeVisible({ timeout: 30000 })
    }

    async selectChartType(namePattern: RegExp): Promise<void> {
        await this.page.keyboard.press('Escape')
        await expect(async () => {
            await this.chartTypeButton.click({ timeout: 500 })
            await this.page.getByRole('menuitem', { name: namePattern }).click({ timeout: 500 })
            await expect(this.chartTypeButton).toHaveText(namePattern, { timeout: 1000 })
        }).toPass({ timeout: 15000 })
        await this.waitForChart()
    }

    async selectDateRange(text: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        const dataAttr = `date-filter-${text.toLowerCase().replace(/\s+/g, '-')}`
        await expect(async () => {
            await this.dateRangeButton.click({ timeout: 500 })
            await this.page.getByTestId(dataAttr).click({ timeout: 500 })
            // Verify the selection actually applied — an edit-mode remount can
            // swallow the click, leaving the old range. Retry the whole open+click.
            await expect(this.dateRangeButton).toContainText(text, { timeout: 1000 })
        }).toPass({ timeout: 15000 })
        await this.waitForChart()
    }

    async selectComparison(text: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        // Maps each dropdown option to the button label it produces. On narrow
        // viewports the button shows a short label ("Previous period" / "No
        // comparison"), so match a substring common to both variants.
        const appliedLabels: Record<string, RegExp> = {
            'No comparison between periods': /no comparison/i,
            'Compare to previous period': /previous period/i,
        }
        const appliedLabel = appliedLabels[text]
        if (!appliedLabel) {
            throw new Error(`selectComparison: no expected button label mapped for option "${text}"`)
        }
        await expect(async () => {
            await this.comparisonButton.click({ timeout: 500 })
            await this.page.getByRole('menuitem', { name: text }).click({ timeout: 500 })
            // Verify the selection actually applied — an edit-mode remount can swallow
            // the click, and the resulting query update is debounced by 500ms. Retry
            // the whole open+click if the button label doesn't change.
            await expect(this.comparisonButton).toContainText(appliedLabel, { timeout: 2000 })
        }).toPass({ timeout: 15000 })
        await this.waitForChart()
    }

    async hoverChartAt(xFraction: number = 0.3, yFraction: number = 0.5): Promise<void> {
        // The quill chart renders two canvases (static `role="img"` layer + an
        // `aria-hidden` hover overlay), so target the static layer to avoid a
        // strict-mode violation. Both share the same box, so hovering it is correct.
        const canvas = this.chart.locator('canvas[role="img"]')
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
