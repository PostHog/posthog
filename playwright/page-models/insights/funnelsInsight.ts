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
        this.verticalChart = page.getByTestId('funnel-steps-bar-chart')
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
        // Scope to the exclusions container — the exclusion row's event picker shares the
        // `trend-element-subject-0` testid with the main series' first step, so a bare
        // `.last()` can land on the wrong control before the exclusion row has rendered.
        const exclusions = this.page.getByTestId('funnel-exclusions-filter')
        const addButton = exclusions.getByRole('button', { name: 'Add exclusion' })
        await addButton.scrollIntoViewIfNeeded()
        await addButton.click()

        const eventButton = exclusions.getByTestId('trend-element-subject-0').last()
        await eventButton.click()
        await this.taxonomicFilter.selectItem(eventName)
        // The exclusion defaults to $pageview; confirm the chosen event actually applied
        // before returning, otherwise the funnel recomputes against the wrong exclusion.
        await expect(eventButton).toContainText(eventName)
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

    async getConversionWindowInterval(): Promise<string> {
        await this.expandFunnelSettings()
        await expect(this.conversionWindowInput).toHaveValue(/\d+/)
        return await this.conversionWindowInput.inputValue()
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

    // The steps chart renders its bars onto a canvas, so the tooltip is driven by
    // hovering the canvas rather than a per-bar DOM element. Retry the move until
    // the tooltip shows, mirroring ChartInsightBase.hoverChartAt.
    async hoverStepBars(): Promise<void> {
        const canvas = this.verticalChart.locator('canvas[role="img"]')
        await expect(canvas).toBeVisible()
        await expect(async () => {
            await canvas.scrollIntoViewIfNeeded()
            const box = (await canvas.boundingBox())!
            await this.page.mouse.move(box.x - 5, box.y - 5)
            await this.page.mouse.move(box.x + box.width * 0.25, box.y + box.height * 0.5)
            await expect(this.tooltip.first()).toBeVisible({ timeout: 1000 })
        }).toPass({ timeout: 15000 })
    }
}
