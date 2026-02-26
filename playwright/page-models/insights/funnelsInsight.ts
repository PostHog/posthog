import { Locator, Page, expect } from '@playwright/test'

export class FunnelsInsight {
    readonly verticalChart: Locator
    readonly horizontalChart: Locator
    readonly chart: Locator
    readonly histogram: Locator
    readonly trendsLineGraph: Locator
    readonly stepLegends: Locator
    readonly layoutSelector: Locator
    readonly stepOrderFilter: Locator
    readonly tooltip: Locator
    readonly taxonomicSearchField: Locator
    readonly taxonomicRows: Locator
    readonly taxonomicExpandRow: Locator
    private readonly conversionWindowSection: Locator

    constructor(private readonly page: Page) {
        this.verticalChart = page.getByTestId('funnel-bar-vertical')
        this.horizontalChart = page.getByTestId('funnel-bar-horizontal')
        this.chart = this.verticalChart.or(this.horizontalChart)
        this.histogram = page.getByTestId('funnel-histogram')
        this.trendsLineGraph = page.getByTestId('trend-line-graph-funnel')
        this.stepLegends = this.verticalChart.locator('.StepLegend')
        this.layoutSelector = page.getByTestId('funnel-bar-layout-selector')
        this.stepOrderFilter = page.getByTestId('funnel-step-order-filter')
        this.tooltip = page.locator('.FunnelTooltip').or(page.locator('.InsightTooltip'))
        this.taxonomicSearchField = page.getByTestId('taxonomic-filter-searchfield')
        this.taxonomicRows = page.locator('.taxonomic-list-row')
        this.taxonomicExpandRow = page.locator('.taxonomic-list-row.expand-row').first()
        this.conversionWindowSection = page
            .locator('div')
            .filter({ hasText: /^Conversion window limit/ })
            .last()
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart.first()).toBeVisible()
    }

    async waitForHistogram(): Promise<void> {
        await expect(this.histogram).toBeVisible()
    }

    async waitForTrendsLineGraph(): Promise<void> {
        await expect(this.trendsLineGraph).toBeVisible()
    }

    async addStep(eventName: string): Promise<void> {
        await this.page.getByRole('button', { name: 'Add step' }).click()
        await this.selectFromTaxonomicFilter(eventName)
    }

    async selectVizType(name: string): Promise<void> {
        const container = this.page
            .locator('div')
            .filter({ hasText: /^Graph type/ })
            .first()
        await container.locator('.LemonSelect').click()
        await this.page.getByRole('menuitem', { name }).click()
    }

    async selectStepEvent(stepIndex: number, eventName: string): Promise<void> {
        await this.page.getByTestId(`trend-element-subject-${stepIndex}`).click()
        await this.selectFromTaxonomicFilter(eventName)
    }

    async addBreakdown(property: string): Promise<void> {
        await this.page.getByTestId('add-breakdown-button').click()
        await this.taxonomicSearchField.waitFor({ state: 'visible' })
        await this.taxonomicSearchField.fill(property)

        // Taxonomic filter shows display names ("Browser" not "$browser")
        const displayName = property.startsWith('$') ? property.slice(1).replace(/_/g, ' ') : property
        const row = this.taxonomicRows.filter({ hasText: new RegExp(displayName, 'i') }).first()

        // The row may be hidden behind a "load more" expand row
        await expect(row.or(this.taxonomicExpandRow)).toBeVisible()
        if ((await this.taxonomicExpandRow.isVisible()) && !(await row.isVisible())) {
            await this.taxonomicExpandRow.click()
            await row.waitFor({ state: 'visible' })
        }
        await row.click()
    }

    async addExclusion(eventName: string): Promise<void> {
        const addButton = this.page.getByRole('button', { name: 'Add exclusion' })
        await addButton.scrollIntoViewIfNeeded()
        await addButton.click()

        await this.page.getByTestId('trend-element-subject-0').last().click()
        await this.selectFromTaxonomicFilter(eventName)
    }

    async selectLayout(label: string): Promise<void> {
        await this.layoutSelector.click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    async selectStepOrder(label: string): Promise<void> {
        await this.stepOrderFilter.click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    async setConversionWindowInterval(value: string): Promise<void> {
        const input = this.conversionWindowSection.locator('input[type="number"]')
        await input.fill(value)
        await input.press('Enter')
    }

    async selectConversionWindowUnit(unit: string): Promise<void> {
        await this.conversionWindowSection.locator('.LemonSelect').click()
        await this.page.getByRole('menuitem', { name: unit }).click()
    }

    async selectAggregation(label: string): Promise<void> {
        const section = this.page
            .locator('div')
            .filter({ hasText: /^Aggregating by/ })
            .last()
        await section.locator('.LemonSelect').click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    stepLegend(index: number): Locator {
        return this.stepLegends.nth(index)
    }

    private async selectFromTaxonomicFilter(name: string): Promise<void> {
        await this.taxonomicSearchField.waitFor({ state: 'visible' })
        await this.taxonomicSearchField.fill(name)
        const row = this.taxonomicRows.filter({ hasText: new RegExp(`^.*${name}.*$`) }).first()
        await row.waitFor({ state: 'visible' })
        await row.click()
    }
}
