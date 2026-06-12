import { Locator, Page, expect } from '@playwright/test'

import { TableHelper } from '../../utils/table-helper'
import { TaxonomicFilter } from '../taxonomicFilter'
import { ChartInsightBase } from './chartInsightBase'

export class StickinessInsight extends ChartInsightBase {
    readonly detailsTable: Locator
    readonly firstSeries: Locator
    readonly secondSeries: Locator
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
        this.taxonomicFilter = new TaxonomicFilter(page)
    }

    seriesEventButton(index: number): Locator {
        return this.page.getByTestId(`trend-element-subject-${index}`)
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

    get details(): TableHelper {
        return new TableHelper(this.detailsTable)
    }
}
