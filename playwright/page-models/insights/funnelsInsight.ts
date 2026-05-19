import { Locator, Page, expect } from '@playwright/test'

import { TaxonomicFilter } from '../taxonomicFilter'

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
    readonly taxonomicFilter: TaxonomicFilter
    readonly conversionWindowInput: Locator
    private readonly conversionWindowSection: Locator

    constructor(private readonly page: Page) {
        this.verticalChart = page.getByTestId('funnel-bar-vertical')
        this.horizontalChart = page.getByTestId('funnel-bar-horizontal')
        this.chart = this.verticalChart.or(this.horizontalChart)
        this.histogram = page.getByTestId('funnel-histogram')
        this.trendsLineGraph = page.getByTestId('trend-line-graph-funnel')
        this.stepLegends = this.verticalChart.getByTestId('funnel-step-legend')
        this.layoutSelector = page.getByTestId('funnel-bar-layout-selector')
        this.stepOrderFilter = page.getByTestId('funnel-step-order-filter')
        this.tooltip = page.getByTestId('funnel-tooltip')
        this.taxonomicFilter = new TaxonomicFilter(page)
        this.conversionWindowSection = page.getByTestId('funnel-conversion-window-filter')
        this.conversionWindowInput = this.conversionWindowSection.getByRole('spinbutton')
    }

    async waitForChart(): Promise<void> {
        await this.page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })
        await expect(this.chart.first()).toBeVisible({ timeout: 30000 })
    }

    private async expandFunnelSettings(): Promise<void> {
        const toggle = this.page.getByTestId('editor-filter-group-collapse-funnel-settings')
        await toggle.waitFor({ state: 'visible' })
        if ((await toggle.getAttribute('title')) === 'Show more') {
            await toggle.click()
        }
    }

    private async expandBreakdownPanel(): Promise<void> {
        const toggle = this.page.getByTestId('editor-filter-group-collapse-breakdown')
        await toggle.waitFor({ state: 'visible' })
        if ((await toggle.getAttribute('title')) === 'Show more') {
            await toggle.click()
        }
    }

    async waitForHistogram(): Promise<void> {
        await expect(this.histogram).toBeVisible()
    }

    async waitForTrendsLineGraph(): Promise<void> {
        await expect(this.trendsLineGraph).toBeVisible()
    }

    async addStep(eventName: string): Promise<void> {
        await this.page.getByRole('button', { name: 'Add step' }).click()
        await this.taxonomicFilter.selectItem(eventName)
    }

    async selectVizType(name: string): Promise<void> {
        await this.page.getByTestId('funnel-viz-type-select').click()
        await this.page.getByRole('menuitem', { name }).click()
    }

    async selectStepEvent(stepIndex: number, eventName: string): Promise<void> {
        await this.page.getByTestId(`trend-element-subject-${stepIndex}`).click()
        await this.taxonomicFilter.selectItem(eventName)
    }

    async addBreakdown(property: string): Promise<void> {
        await this.expandBreakdownPanel()
        await this.page.getByTestId('add-breakdown-button').click()
        await this.taxonomicFilter.selectItem(property)
    }

    async addExclusion(eventName: string): Promise<void> {
        await this.expandFunnelSettings()
        const addButton = this.page.getByRole('button', { name: 'Add exclusion' })
        await addButton.scrollIntoViewIfNeeded()
        await addButton.click()

        await this.page.getByTestId('trend-element-subject-0').last().click()
        await this.taxonomicFilter.selectItem(eventName)
    }

    async selectLayout(label: string): Promise<void> {
        await this.layoutSelector.click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    async selectStepOrder(label: string): Promise<void> {
        await this.expandFunnelSettings()
        await this.stepOrderFilter.click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    async setConversionWindowInterval(value: string): Promise<void> {
        await this.expandFunnelSettings()
        const input = this.conversionWindowSection.getByRole('spinbutton')
        await input.fill(value)
        await input.press('Enter')
    }

    async selectConversionWindowUnit(unit: string): Promise<void> {
        await this.expandFunnelSettings()
        await this.conversionWindowSection.getByTestId('funnel-conversion-window-unit').click()
        await this.page.getByRole('menuitem', { name: unit }).click()
    }

    async selectAggregation(label: string): Promise<void> {
        await this.expandFunnelSettings()
        await this.page.getByTestId('funnel-aggregation-filter').getByTestId('retention-aggregation-selector').click()
        await this.page.getByRole('menuitem', { name: label }).click()
    }

    stepLegend(index: number): Locator {
        return this.stepLegends.nth(index)
    }
}
