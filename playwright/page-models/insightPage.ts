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

    // insight types
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

    chartFor(type: InsightType): Locator {
        const locators: Record<string, Locator> = {
            [InsightType.TRENDS]: this.trends.chart,
            [InsightType.FUNNELS]: this.funnels.chart,
            [InsightType.RETENTION]: this.retention.chart,
            [InsightType.PATHS]: this.paths.chart,
            [InsightType.STICKINESS]: this.stickiness.chart,
            [InsightType.LIFECYCLE]: this.lifecycle.chart,
            [InsightType.SQL]: this.sql.chart,
        }
        return locators[type] ?? this.trends.chart
    }

    async goToList(): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights(), { waitUntil: 'domcontentloaded' })
        return this
    }

    async goToNew(insightType?: InsightType): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights(), { waitUntil: 'domcontentloaded' })
        await this.page.getByTestId('saved-insights-new-insight-dropdown').click()

        const insightQuery = this.page.waitForRequest((req) => {
            return !!(req.url().match(/api\/environments\/\d+\/query/) && req.method() === 'POST')
        })
        await this.page.locator(`[data-attr-insight-type="${insightType || 'TRENDS'}"]`).click()
        await insightQuery

        await this.page.waitForSelector('.LemonTabs__tab--active')
        return this
    }

    async goToNewTrends(): Promise<InsightPage> {
        await this.page.goto(urls.insightNew({ type: InsightType.TRENDS }), { waitUntil: 'domcontentloaded' })
        await this.page.waitForSelector('.LemonTabs__tab--active')
        return this
    }

    async createNew(insightName?: string, insightType?: InsightType): Promise<InsightPage> {
        await this.goToNew(insightType)
        await this.editName(insightName)
        await this.save()
        return this
    }

    async save(): Promise<void> {
        await this.saveButton.click()
        await this.page.waitForURL(/^(?!.*\/new$).+$/)
        await this.page.waitForSelector('[data-attr="insight-edit-button"]', { state: 'visible' })
    }

    async edit(): Promise<void> {
        await this.editButton.click()
    }

    async withEdit(callback: () => Promise<void>): Promise<void> {
        await this.edit()
        await callback()
        await this.save()
    }

    async withReload(callback: () => Promise<void>, beforeFn?: () => Promise<void>): Promise<void> {
        await beforeFn?.()
        await callback()
        await this.page.reload({ waitUntil: 'networkidle' })
        await callback()
    }

    async editName(insightName: string = randomString('insight')): Promise<void> {
        const nameField = this.page.getByTestId('scene-title-textarea')
        await nameField.click()
        await nameField.fill(insightName)
        await nameField.blur()
    }

    async delete(): Promise<void> {
        await this.page.getByTestId('more-button').click()
        await this.page.getByTestId('delete-insight-from-insight-view').click()
        await expect(this.page.locator('.saved-insights')).toBeVisible()
    }

    async duplicate(): Promise<void> {
        await this.page.getByTestId('more-button').click()
        await this.page.getByTestId('duplicate-insight-from-insight-view').click()
    }

    async openPersonsModal(): Promise<void> {
        await this.page.locator('.TrendsInsight .LineGraph').click()
        await this.page.locator('[data-attr="persons-modal"]').waitFor({ state: 'visible' })
    }

    async dismissQuickStartIfVisible(): Promise<void> {
        const minimizeButton = this.page.getByText('Minimize')
        if (await minimizeButton.isVisible({ timeout: 2000 }).catch(() => false)) {
            await minimizeButton.click()
        }
    }
}

class TrendsInsight {
    readonly chart: Locator
    readonly detailsTable: Locator
    readonly detailsLabels: Locator
    readonly detailsLoader: Locator
    readonly addSeriesButton: Locator
    readonly firstSeries: Locator
    readonly secondSeries: Locator
    readonly breakdownButton: Locator
    readonly formulaSwitch: Locator
    readonly formulaInput: Locator
    readonly addFormulaButton: Locator
    readonly dateRangeButton: Locator
    readonly chartTypeButton: Locator
    readonly comparisonButton: Locator

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
        await expect(this.chart).toBeVisible()
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
        await this.page.locator('.taxonomic-list-row').first().click()
    }

    async setFormula(formula: string): Promise<void> {
        await this.formulaSwitch.click()
        await this.addFormulaButton.click()
        await this.formulaInput.first().waitFor({ state: 'visible' })
        await this.formulaInput.first().fill(formula)
        await this.formulaInput.first().press('Enter')
    }
}

class FunnelsInsight {
    readonly chart: Locator
    readonly stepBars: Locator

    constructor(private readonly page: Page) {
        this.chart = page.locator('[data-attr="funnel-bar-vertical"]')
        this.stepBars = page.locator('.StepBar')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}

class RetentionInsight {
    readonly chart: Locator
    readonly table: Locator

    constructor(page: Page) {
        this.chart = page.locator('.RetentionContainer')
        this.table = page.locator('[data-attr="retention-table"]')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}

class PathsInsight {
    readonly chart: Locator
    readonly container: Locator

    constructor(page: Page) {
        this.chart = page.locator('.Paths svg.Paths__canvas')
        this.container = page.locator('.Paths')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}

class StickinessInsight {
    readonly chart: Locator
    readonly detailsLabels: Locator
    readonly detailsLoader: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('insights-graph')
        this.detailsLabels = page.getByTestId('insights-table-graph').locator('.insights-label')
        this.detailsLoader = page.locator('.LemonTableLoader')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsLabels.first().waitFor()
        await expect(this.detailsLoader).toHaveCount(0)
    }
}

class LifecycleInsight {
    readonly chart: Locator

    constructor(page: Page) {
        this.chart = page.getByTestId('insights-graph')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }
}

class SqlInsight {
    readonly chart: Locator
    readonly runButton: Locator

    constructor(private readonly page: Page) {
        this.chart = page.locator('[data-attr="hogql-query-editor"]')
        this.runButton = page.getByTestId('sql-editor-run-button')
    }

    async waitForChart(): Promise<void> {
        await expect(this.chart).toBeVisible()
    }

    async writeQuery(query: string): Promise<void> {
        const editor = this.chart.locator('.monaco-editor')
        await expect(editor).toBeVisible()
        await editor.click()

        await this.page.keyboard.press('ControlOrMeta+KeyA')
        await this.page.keyboard.press('Backspace')
        await this.page.keyboard.insertText(query)
    }

    async run(): Promise<void> {
        await this.runButton.click()
    }
}
