import { Locator, Page, expect } from '@playwright/test'

import { TableHelper } from '../../utils/table-helper'
import { TaxonomicFilter } from '../taxonomicFilter'
import { ChartInsightBase } from './chartInsightBase'

export class StickinessInsight extends ChartInsightBase {
    readonly detailsTable: Locator
    readonly firstSeries: Locator
    readonly secondSeries: Locator
    readonly dateRangeButton: Locator
    readonly chartTypeButton: Locator
    readonly comparisonButton: Locator
    readonly taxonomicFilter: TaxonomicFilter

    private readonly detailsLoader: Locator
    private readonly addSeriesButton: Locator

    constructor(page: Page) {
        super(page, page.getByTestId('insights-graph'))

        this.detailsTable = page.getByTestId('insights-table-graph')
        this.detailsLoader = page.locator('.LemonTableLoader')
        this.addSeriesButton = page.getByTestId('add-action-event-button')
        this.firstSeries = page.getByTestId('trend-element-subject-0')
        this.secondSeries = page.getByTestId('trend-element-subject-1')
        this.dateRangeButton = page.getByTestId('date-filter')
        this.chartTypeButton = page.getByTestId('chart-filter')
        this.comparisonButton = page.getByTestId('compare-filter')
        this.taxonomicFilter = new TaxonomicFilter(page)
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

    async selectComparison(text: string): Promise<void> {
        await this.comparisonButton.click()
        await this.page.getByText(text).click()
        await this.waitForChart()
    }

    get details(): TableHelper {
        return new TableHelper(this.detailsTable)
    }
}
