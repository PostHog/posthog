import { Locator, Page, expect } from '@playwright/test'

export class RetentionInsight {
    readonly chart: Locator
    readonly table: Locator
    readonly tableHeaders: Locator
    readonly tableRows: Locator
    readonly conditionPanel: Locator
    readonly optionsPanel: Locator
    readonly breakdownButton: Locator
    readonly alertsButton: Locator
    readonly chartFilter: Locator
    readonly tooltip: Locator
    readonly personsModal: Locator
    readonly customBracketsCheckbox: Locator
    readonly sectionHeaders: Locator

    constructor(private readonly page: Page) {
        this.chart = page.getByTestId('trend-line-graph')
        this.table = page.getByTestId('retention-table')
        this.tableHeaders = this.table.locator('th')
        this.tableRows = this.table.locator('tr')
        this.conditionPanel = page.locator('[data-attr="retention-condition"]')
        this.optionsPanel = page.locator('[data-attr="retention-options"]')
        this.breakdownButton = page.getByTestId('add-breakdown-button')
        this.alertsButton = page.getByTestId('insight-alerts-dropdown-menu-item')
        this.chartFilter = page.getByTestId('chart-filter')
        this.tooltip = page.locator('.InsightTooltip')
        this.personsModal = page
            .locator('.LemonModal')
            .filter({ has: page.locator('.RetentionTable--non-interactive') })
        this.customBracketsCheckbox = page.locator('.LemonCheckbox', { hasText: 'Use custom return ranges' })
        this.sectionHeaders = this.table.locator('tr.cursor-pointer')
    }

    async selectTargetEvent(eventName: string): Promise<void> {
        const button = this.conditionPanel.getByTestId('trend-element-subject-0').nth(0)
        await this.pickEventFromButton(button, eventName)
        await this.waitForChart()
        await expect(button).toContainText(eventName, { timeout: 5000 })
    }

    async selectReturningEvent(eventName: string): Promise<void> {
        const button = this.conditionPanel.getByTestId('trend-element-subject-0').nth(1)
        await this.pickEventFromButton(button, eventName)
        await this.waitForChart()
        await expect(button).toContainText(eventName, { timeout: 5000 })
    }

    private async pickEventFromButton(button: Locator, eventName: string): Promise<void> {
        await expect(async () => {
            await this.page.keyboard.press('Escape')
            await button.scrollIntoViewIfNeeded()
            await button.click()
            const searchField = this.page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible', timeout: 3000 })
            await searchField.fill(eventName)
            const row = this.page.locator('.taxonomic-list-row', { hasText: eventName })
            await row.first().click()
        }).toPass({ timeout: 30000 })
    }

    async waitForChart(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.table).toBeVisible()
    }

    async selectPeriod(period: 'days' | 'weeks' | 'months'): Promise<void> {
        const periodButton = this.conditionPanel.locator('button.LemonSelect', { hasText: /^(days|weeks|months)$/ })
        await periodButton.scrollIntoViewIfNeeded()
        await periodButton.click()
        const menuItem = this.page.getByRole('menuitem', { name: period })
        await menuItem.waitFor({ state: 'visible' })
        await menuItem.click()
        const periodLabel = period.slice(0, 1).toUpperCase() + period.slice(1, -1)
        await expect(this.tableHeaders.filter({ hasText: new RegExp(`^${periodLabel} \\d`) }).first()).toBeVisible({
            timeout: 30000,
        })
    }

    async toggleCumulative(): Promise<void> {
        const toggle = this.optionsPanel.locator('.LemonSegmentedButton li', { hasText: 'on or after' })
        await toggle.scrollIntoViewIfNeeded()
        await toggle.click()
        await this.waitForChart()
    }

    async addBreakdown(property: string): Promise<void> {
        await expect(async () => {
            await this.page.keyboard.press('Escape')
            await this.breakdownButton.click()
            const searchField = this.page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible', timeout: 3000 })
            await searchField.fill(property)
            const row = this.page.locator('.taxonomic-list-row').first()
            await row.waitFor({ state: 'visible', timeout: 5000 })
            await row.click()
        }).toPass({ timeout: 30000 })
        await this.waitForChart()
    }

    async hoverChartAt(xFraction: number, yFraction: number): Promise<void> {
        const canvas = this.chart.locator('canvas')
        await expect(canvas).toBeVisible()
        await expect(async () => {
            const box = (await canvas.boundingBox())!
            await this.page.mouse.move(box.x - 5, box.y - 5)
            await this.page.mouse.move(box.x + box.width * xFraction, box.y + box.height * yFraction)
            await expect(this.tooltip).toBeVisible({ timeout: 1000 })
        }).toPass({ timeout: 15000 })
    }

    get detailRows(): Locator {
        return this.table.locator('tr:not(.cursor-pointer)').filter({ hasNot: this.page.locator('th') })
    }

    async getCohortSizes(): Promise<number[]> {
        const rows = this.detailRows
        const count = await rows.count()
        const sizes: number[] = []
        for (let i = 0; i < count; i++) {
            const text = await rows.nth(i).locator('.RetentionTable__TextTab').textContent()
            sizes.push(Number(text))
        }
        return sizes
    }

    async getCellPercentages(rowIndex: number): Promise<string[]> {
        const row = this.detailRows.nth(rowIndex)
        return row.locator('.RetentionTable__Tab').allTextContents()
    }

    async getColumnHeaderTexts(): Promise<string[]> {
        return this.tableHeaders.allTextContents()
    }

    async clickCohortRow(rowIndex: number): Promise<void> {
        const row = this.detailRows.nth(rowIndex)
        await expect(row).toBeVisible({ timeout: 15000 })
        await expect(async () => {
            await this.page.keyboard.press('Escape')
            await row.scrollIntoViewIfNeeded()
            await row.click()
            await expect(this.personsModal).toBeVisible({ timeout: 5000 })
        }).toPass({ timeout: 30000 })
    }

    async closePersonsModal(): Promise<void> {
        await this.personsModal.locator('button[aria-label="close"]').click()
        await expect(this.personsModal).not.toBeVisible()
    }

    private get customBracketsBox(): Locator {
        return this.customBracketsCheckbox.locator('.LemonCheckbox__box')
    }

    async enableCustomBrackets(): Promise<void> {
        await this.customBracketsBox.scrollIntoViewIfNeeded()
        await this.customBracketsBox.click()
        await this.addBracketButton.waitFor({ state: 'visible' })
    }

    async disableCustomBrackets(): Promise<void> {
        await this.customBracketsBox.scrollIntoViewIfNeeded()
        await this.customBracketsBox.click()
        await this.addBracketButton.waitFor({ state: 'hidden' })
        await this.waitForChart()
    }

    private get addBracketButton(): Locator {
        return this.conditionPanel.getByRole('button', { name: 'Add another bracket' })
    }

    private get bracketInputs(): Locator {
        return this.conditionPanel.locator('.flex.items-center.gap-2:has(.w-24) .LemonInput input')
    }

    async setCustomBracket(index: number, value: number): Promise<void> {
        const input = this.bracketInputs.nth(index)
        await input.fill(String(value))
        await input.press('Tab')
    }

    async addCustomBracket(): Promise<void> {
        await this.addBracketButton.click()
    }
}
