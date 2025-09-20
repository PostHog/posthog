import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { randomString } from '../utils'
import { DashboardPage } from './dashboardPage'

export class InsightPage {
    readonly saveButton: Locator
    readonly editButton: Locator
    readonly topBarName: Locator

    // series
    readonly addEntityButton: Locator
    readonly firstEntity: Locator
    readonly secondEntity: Locator

    // details table
    readonly detailsLabels: Locator
    readonly detailsLoader: Locator

    // menu
    readonly moreButton: Locator
    readonly toggleEditorButton: Locator

    // dashboard
    readonly dashboardButton: Locator

    // source editor
    readonly editor: Locator
    readonly updateSourceButton: Locator

    constructor(private readonly page: Page) {
        this.saveButton = page.getByTestId('insight-save-button')
        this.editButton = page.getByTestId('insight-edit-button')
        this.topBarName = page.getByTestId('top-bar-name')

        this.addEntityButton = page.getByTestId('add-action-event-button')
        this.firstEntity = page.getByTestId('trend-element-subject-0')
        this.secondEntity = page.getByTestId('trend-element-subject-1')

        this.detailsLabels = page.getByTestId('insights-table-graph').locator('.insights-label')
        this.detailsLoader = page.locator('.LemonTableLoader')

        this.moreButton = page.getByTestId('more-button')
        this.toggleEditorButton = page.getByTestId('show-insight-source')

        this.dashboardButton = page.getByTestId('save-to-dashboard-button')

        this.editor = this.page.getByTestId('query-editor').locator('.monaco-editor')
        this.updateSourceButton = page.getByRole('button', { name: 'Update and run' })
    }

    async goToNew(insightType?: InsightType): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights())
        await this.page.getByTestId('saved-insights-new-insight-dropdown').click()

        const insightQuery = this.page.waitForRequest((req) => {
            return !!(req.url().match(/api\/environments\/\d+\/query/) && req.method() === 'POST')
        })
        await this.page.locator(`[data-attr-insight-type="${insightType || 'TRENDS'}"]`).click()
        await insightQuery

        await this.page.waitForSelector('.LemonTabs__tab--active')
        return this
    }

    async createNew(insightName?: string, insightType?: InsightType): Promise<InsightPage> {
        await this.goToNew(insightType)
        await this.editName(insightName)
        await this.save()
        return this
    }

    /*
     * Filters
     */
    async save(): Promise<void> {
        await this.saveButton.click()
        // wait for save to complete and URL to change and include short id
        await this.page.waitForURL(/^(?!.*\/new$).+$/)
        await this.page.waitForSelector('[data-attr="insight-edit-button"]', { state: 'visible' })
    }

    async edit(): Promise<void> {
        await this.editButton.click()
    }

    /** Enables edit mode, performs actions and saves. */
    async withEdit(callback: () => Promise<void>): Promise<void> {
        await this.edit()
        await callback()
        await this.save()
    }

    /** Checks assertions, reloads and checks again. This is useful for asserting both the local state
     * and the backend side state are persisted correctly. */
    async withReload(callback: () => Promise<void>, beforeFn?: () => Promise<void>): Promise<void> {
        await beforeFn?.()
        await callback()
        await this.page.reload({ waitUntil: 'networkidle' })
        await callback()
    }

    async waitForDetailsTable(): Promise<void> {
        await this.detailsLabels.first().waitFor()
        await expect(this.detailsLoader).toHaveCount(0)
    }

    /*
     * Metadata
     */
    async editName(insightName: string = randomString('insight')): Promise<void> {
        await this.topBarName.getByRole('button').click()
        await this.topBarName.getByRole('textbox').fill(insightName)
        await this.topBarName.getByRole('button').getByText('Save').click()
    }

    /*
     * Query editor
     */
    async openSourceEditor(): Promise<void> {
        await this.moreButton.click()
        await this.toggleEditorButton.click()
    }

    async changeQuerySource(code: string): Promise<void> {
        await this.editor.click()

        // clear text
        await this.page.keyboard.press('Control+KeyA')
        await this.page.keyboard.press('Backspace')

        // insert text
        await this.page.keyboard.insertText(code)

        await this.updateSourceButton.click()
    }

    /*
     * More menu
     */
    async delete(): Promise<void> {
        await this.moreButton.click()
        await this.page.getByTestId('delete-insight-from-insight-view').click()
        await expect(this.page.locator('.saved-insights')).toBeVisible()
    }

    async duplicate(): Promise<void> {
        await this.moreButton.click()
        await this.page.getByTestId('duplicate-insight-from-insight-view').click()
    }

    /*
     * Dashboards
     */
    async addToNewDashboard(dashboardName?: string): Promise<void> {
        await this.dashboardButton.click()
        await this.page.locator('.LemonModal').getByText('Add to a new dashboard').click()
        await this.page.getByTestId('create-dashboard-blank').click()
        await expect(this.page.locator('.dashboard')).toBeVisible()

        if (dashboardName) {
            await new DashboardPage(this.page).editName(dashboardName)
        }
    }

    async removeDashboard(dashboardName?: string): Promise<void> {
        await this.dashboardButton.click()
        if (dashboardName) {
            await this.page.getByTestId('dashboard-searchfield').fill(dashboardName)
        }
        await this.page.getByText('Remove from dashboard').first().click()
    }

    async openDashboard(dashboardName: string): Promise<void> {
        await this.dashboardButton.click()
        await this.page.getByTestId('dashboard-searchfield').fill(dashboardName)
        await this.page.getByTestId('dashboard-list-item').getByRole('link').first().click()
    }

    async openPersonsModal(): Promise<void> {
        await this.page.locator('.TrendsInsight .LineGraph').click()
        await this.page.locator('[data-attr="persons-modal"]').waitFor({ state: 'visible' })
    }
}
