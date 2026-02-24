import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { randomString } from '../utils'

export class InsightPage {
    readonly page: Page

    // top bar
    readonly saveButton: Locator
    readonly editButton: Locator
    readonly topBarName: Locator
    readonly activeTab: Locator

    readonly trends: TrendsInsight
    readonly funnels: FunnelsInsight
    readonly retention: RetentionInsight
    readonly paths: PathsInsight
    readonly stickiness: StickinessInsight
    readonly lifecycle: LifecycleInsight
    readonly sql: SqlInsight

    constructor(page: Page) {
        this.page = page

        this.saveButton = page.getByTestId('insight-save-button')
        this.editButton = page.getByTestId('insight-edit-button')
        this.topBarName = page.locator('.scene-name')
        this.activeTab = page.locator('.LemonTabs__tab--active')

        this.trends = new TrendsInsight(page)
        this.funnels = new FunnelsInsight(page)
        this.retention = new RetentionInsight(page)
        this.paths = new PathsInsight(page)
        this.stickiness = new StickinessInsight(page)
        this.lifecycle = new LifecycleInsight(page)
        this.sql = new SqlInsight(page)
    }

    async goToList(): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights(), { waitUntil: 'domcontentloaded' })
        return this
    }

    async goToNewInsight(type: InsightType): Promise<InsightPage> {
        await this.page.goto(urls.insightNew({ type }), { waitUntil: 'domcontentloaded' })
        await this.page.waitForSelector('.LemonTabs__tab--active')
        return this
    }

    async goToNewTrends(): Promise<InsightPage> {
        return this.goToNewInsight(InsightType.TRENDS)
    }

    async goToSql(): Promise<InsightPage> {
        await this.page.goto('/sql', { waitUntil: 'domcontentloaded' })
        return this
    }

    async save(): Promise<void> {
        await this.saveButton.click()
        await this.page.waitForURL(/^(?!.*\/new$).+$/)
        await expect(this.editButton).toBeVisible()
    }

    async edit(): Promise<void> {
        await this.editButton.click()
    }

    async editName(insightName: string = randomString('insight')): Promise<void> {
        const nameField = this.page.getByTestId('scene-title-textarea')
        await expect(nameField).toBeVisible()
        await nameField.click()
        await nameField.fill(insightName)
        await nameField.blur()
    }

    async createNew(name: string, type: InsightType): Promise<InsightPage> {
        await this.goToNewInsight(type)
        await this.editName(name)
        return this
    }

    async goToNew(type: InsightType): Promise<InsightPage> {
        return this.goToNewInsight(type)
    }

    async openPersonsModal(): Promise<void> {
        await this.page.locator('.TrendsInsight canvas').click()
        await this.page.waitForSelector('[data-attr="persons-modal"]', { state: 'visible' })
    }

    async saveAsNew(name: string): Promise<void> {
        const originalUrl = this.page.url()
        await this.page.locator('[data-attr="insight-save-dropdown"]').click()
        await this.page.locator('[data-attr="insight-save-as-new-insight"]').click()
        const nameInput = this.page.getByPlaceholder('Please enter the new name')
        await nameInput.waitFor({ state: 'visible' })
        await nameInput.fill(name)
        await this.page.getByRole('button', { name: 'Submit' }).click()
        await this.page.waitForURL((url) => url.toString() !== originalUrl, { timeout: 15000 })
    }
}

class TrendsInsight {
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

class FunnelsInsight {
    readonly chart: Locator
    readonly stepBars: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('funnel-bar-vertical').or(page.getByTestId('funnel-bar-horizontal'))
        this.stepBars = page.getByTestId('funnel-bar-vertical').locator('.StepLegend')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart.first()).toBeVisible()
    }
}

class RetentionInsight {
    readonly chart: Locator
    readonly table: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('trend-line-graph')
        this.table = page.getByTestId('retention-table')
    }

    async waitForChart(): Promise<void> {
        await expect(this.table).toBeVisible()
    }
}

class PathsInsight {
    readonly container: Locator

    constructor(page: Page) {
        this.container = page.getByTestId('paths-viz')
    }

    async waitForChart(): Promise<void> {
        await expect(this.container).toBeVisible()
    }
}

class StickinessInsight {
    readonly chart: Locator
    readonly detailsTable: Locator

    private readonly detailsLoader: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('insights-graph')
        this.detailsTable = page.getByTestId('insights-table-graph')
        this.detailsLoader = page.locator('.LemonTableLoader')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsTable.waitFor({ state: 'visible' })
        await expect(this.detailsLoader).toHaveCount(0)
    }
}

class LifecycleInsight {
    readonly chart: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('trend-line-graph')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}

class SqlInsight {
    readonly editor: Locator
    readonly runButton: Locator

    constructor(private readonly page: Page) {
        this.editor = page.getByTestId('editor-scene')
        this.runButton = page.getByTestId('sql-editor-run-button')
    }

    async waitForChart(): Promise<void> {
        await expect(this.editor).toBeVisible()
    }

    async writeQuery(query: string): Promise<void> {
        const editorArea = this.page.getByTestId('hogql-query-editor')
        await editorArea.waitFor({ state: 'visible' })
        await editorArea.click()
        await this.page.keyboard.press('Meta+A')
        await this.page.keyboard.type(query)
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
