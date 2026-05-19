import { Locator, Page, expect } from '@playwright/test'

import { TableHelper } from '../../utils/table-helper'
import { TaxonomicFilter } from '../taxonomicFilter'
import { ChartInsightBase } from './chartInsightBase'

export class TrendsInsight extends ChartInsightBase {
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
    readonly taxonomicFilter: TaxonomicFilter
    readonly boldNumber: Locator
    readonly boldNumberComparison: Locator

    private readonly detailsLoader: Locator
    private readonly addSeriesButton: Locator
    private readonly addFormulaButton: Locator

    constructor(page: Page) {
        super(page, page.getByTestId('insights-graph'))

        this.detailsTable = page.getByTestId('insights-table-graph')
        this.detailsLabels = this.detailsTable.getByTestId('insight-label')
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
        this.taxonomicFilter = new TaxonomicFilter(page)
        this.boldNumber = page.getByTestId('bold-number-value')
        this.boldNumberComparison = page.getByTestId('bold-number-comparison')
    }

    seriesEventButton(index: number): Locator {
        return this.page.getByTestId(`trend-element-subject-${index}`)
    }

    async waitForChart(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.chart).toBeVisible({ timeout: 30000 })
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsTable.locator('tbody tr').first().waitFor()
        await expect(this.detailsLoader).toHaveCount(0)
    }

    async addSeries(): Promise<void> {
        await this.addSeriesButton.click()
    }

    async selectEvent(seriesIndex: number, eventName: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        await this.seriesEventButton(seriesIndex).click()
        await this.taxonomicFilter.selectItem(eventName)
    }

    async addBreakdown(property: string): Promise<void> {
        await this.expandBreakdownPanel()
        await this.breakdownButton.click()
        await this.taxonomicFilter.selectItem(property)
    }

    private async expandBreakdownPanel(): Promise<void> {
        const toggle = this.page.getByTestId('editor-filter-group-collapse-breakdown')
        await toggle.waitFor({ state: 'visible' })
        if ((await toggle.getAttribute('title')) === 'Show more') {
            await toggle.click()
        }
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

    mathPropertySelect(): Locator {
        return this.page.getByTestId('math-property-select')
    }

    async selectMath(seriesIndex: number, mathName: string): Promise<void> {
        await this.mathSelector(seriesIndex).click()
        await this.page.getByRole('menuitem', { name: mathName }).click()
        await this.waitForChart()
    }

    async selectMathWithAggregation(seriesIndex: number, mathName: RegExp, aggregation: string): Promise<void> {
        await this.mathSelector(seriesIndex).click()
        const mathItem = this.page.getByRole('menuitem', { name: mathName })
        await mathItem.waitFor({ state: 'visible' })
        await mathItem.getByRole('button').click()
        await this.page.getByRole('menuitem', { name: aggregation }).click()
        await this.waitForChart()
    }

    async selectMathProperty(property: string): Promise<void> {
        await this.page.keyboard.press('Escape')
        await this.mathPropertySelect().click()
        await this.taxonomicFilter.selectItem(property)
        await this.waitForChart()
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
        }).toPass({ timeout: 15000 })
        await this.waitForChart()
    }

    async openOptionsPanel(): Promise<void> {
        await this.page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
    }

    async duplicateSeries(seriesIndex: number): Promise<void> {
        await this.seriesEventButton(seriesIndex).hover()
        await this.page.getByTestId(`more-button-${seriesIndex}`).click()
        await this.page.getByTestId(`show-prop-duplicate-${seriesIndex}`).click()
    }

    async deleteSeries(seriesIndex: number): Promise<void> {
        await this.seriesEventButton(seriesIndex).hover()
        await this.page.getByTestId(`more-button-${seriesIndex}`).click()
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
        await this.page.keyboard.press('Escape')
        await this.expandBreakdownPanel()
        const tag = this.page.getByTestId('breakdown-tag').nth(index)
        await tag.getByTestId('breakdown-tag-close').click()
        await expect(tag).not.toBeVisible()
        await this.waitForChart()
    }

    async selectTaxonomicTab(groupType: string): Promise<void> {
        await this.taxonomicFilter.selectTab(groupType)
    }

    taxonomicResults(): Locator {
        return this.taxonomicFilter.rows
    }

    get details(): TableHelper {
        return new TableHelper(this.detailsTable)
    }
}
