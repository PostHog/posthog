import { Locator, Page, expect } from '@playwright/test'

export class TrendsInsight {
    readonly chart: Locator
    readonly detailsTable: Locator
    readonly detailsLabels: Locator
    readonly firstSeries: Locator
    readonly secondSeries: Locator
    readonly breakdownButton: Locator
    readonly formulaSwitch: Locator
    readonly formulaInput: Locator
    readonly dateRangeButton: Locator
    readonly chartTypeButton: Locator
    readonly comparisonButton: Locator

    private readonly detailsLoader: Locator
    private readonly addSeriesButton: Locator
    private readonly addFormulaButton: Locator

    constructor(private readonly page: Page) {
        this.chart = page.getByTestId('insights-graph')

        this.detailsTable = page.getByTestId('insights-table-graph')
        this.detailsLabels = this.detailsTable.locator('.insights-label')
        this.detailsLoader = page.locator('.LemonTableLoader')
        this.addSeriesButton = page.getByTestId('add-action-event-button')
        this.firstSeries = page.getByTestId('trend-element-subject-0')
        this.secondSeries = page.getByTestId('trend-element-subject-1')
        this.breakdownButton = page.getByTestId('add-breakdown-button')
        this.formulaSwitch = page.locator('#trends-formula-switch')
        this.formulaInput = page.getByPlaceholder('Example: (A + B) / 100')
        this.addFormulaButton = page.getByRole('button', { name: 'Add formula' })
        this.dateRangeButton = page.getByTestId('date-filter')
        this.chartTypeButton = page.getByTestId('chart-filter')
        this.comparisonButton = page.getByTestId('compare-filter')
    }

    seriesEventButton(index: number): Locator {
        return this.page.getByTestId(`trend-element-subject-${index}`)
    }

    async waitForChart(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.chart).toBeVisible({ timeout: 30000 })
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsLabels.first().waitFor()
        await expect(this.detailsLoader).toHaveCount(0)
    }

    async addSeries(): Promise<void> {
        await this.addSeriesButton.click()
    }

    async selectEvent(seriesIndex: number, eventName: string): Promise<void> {
        await this.seriesEventButton(seriesIndex).click()
        const searchField = this.page.getByTestId('taxonomic-filter-searchfield')
        await searchField.waitFor({ state: 'visible' })
        await searchField.fill(eventName)
        await this.page.locator('.taxonomic-list-row').first().click()
    }

    async addBreakdown(property: string): Promise<void> {
        await this.breakdownButton.click()
        const searchField = this.page.getByTestId('taxonomic-filter-searchfield')
        await searchField.waitFor({ state: 'visible' })
        await searchField.fill(property)
        const row = this.page.locator('.taxonomic-list-row').first()
        await row.waitFor({ state: 'visible', timeout: 15000 })
        await row.click()
    }

    async setFormula(formula: string): Promise<void> {
        await this.formulaSwitch.click()
        await this.addFormulaButton.click()
        await this.formulaInput.first().waitFor({ state: 'visible' })
        await this.formulaInput.first().fill(formula)
        await this.formulaInput.first().press('Enter')
    }

    mathSelector(seriesIndex: number): Locator {
        return this.page.getByTestId(`math-selector-${seriesIndex}`)
    }

    async selectChartType(namePattern: RegExp): Promise<void> {
        await this.chartTypeButton.click()
        await this.page.getByRole('menuitem', { name: namePattern }).click()
        await this.waitForChart()
    }

    async selectDateRange(text: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        const dataAttr = `date-filter-${text.toLowerCase().replace(/\s+/g, '-')}`
        // The insight page re-renders a lot, detaching DOM nodes.
        // Retry the full open+click sequence with force (skips scroll and
        // stability checks) until both clicks land in a stable window.
        await expect(async () => {
            await this.dateRangeButton.click({ force: true, timeout: 500 })
            await this.page.getByTestId(dataAttr).click({ force: true, timeout: 500 })
        }).toPass({ timeout: 15000 })
        await this.waitForChart()
    }

    async openOptionsPanel(): Promise<void> {
        await this.page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
    }

    async duplicateSeries(seriesIndex: number): Promise<void> {
        await this.seriesEventButton(seriesIndex).hover()
        await this.page.getByTestId(`more-button-${seriesIndex}`).click({ force: true })
        await this.page.getByTestId(`show-prop-duplicate-${seriesIndex}`).click()
    }

    async deleteSeries(seriesIndex: number): Promise<void> {
        await this.seriesEventButton(seriesIndex).hover()
        await this.page.getByTestId(`more-button-${seriesIndex}`).click({ force: true })
        await this.page.getByRole('button', { name: 'Delete' }).click()
        await this.waitForChart()
    }

    async selectInterval(interval: string): Promise<void> {
        await this.page.getByTestId('interval-filter').click()
        await this.page.getByRole('menuitem', { name: interval }).click()
        await this.waitForChart()
    }

    async unpinInterval(): Promise<void> {
        await this.page.getByRole('button', { name: 'Unpin interval' }).click()
        await this.waitForChart()
    }

    async selectComparison(text: string): Promise<void> {
        await this.comparisonButton.click()
        await this.page.getByText(text).click()
        await this.waitForChart()
    }

    async removeBreakdown(index: number = 0): Promise<void> {
        const tag = this.page.locator('.BreakdownTag').nth(index)
        await tag.hover()
        await tag.locator('[aria-label="close"]').or(tag.locator('button')).last().click({ force: true })
        await this.waitForChart()
    }

    async selectTaxonomicTab(groupType: string): Promise<void> {
        await this.page.getByTestId(`taxonomic-tab-${groupType}`).last().click()
    }

    taxonomicResults(): Locator {
        return this.page.locator('.taxonomic-list-row')
    }
}
