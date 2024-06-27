import { Locator, Page } from '@playwright/test'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { randomString } from '../utils'

export class InsightPage {
    readonly page: Page
    readonly saveButton: Locator
    readonly editButton: Locator
    readonly topBarName: Locator
    readonly detailLabels: Locator
    readonly addEntityButton: Locator
    readonly firstEntity: Locator
    readonly secondEntity: Locator

    constructor(page: Page) {
        this.page = page

        this.saveButton = page.getByTestId('insight-save-button')
        this.editButton = page.getByTestId('insight-edit-button')
        this.topBarName = page.getByTestId('top-bar-name')
        this.detailLabels = page.getByTestId('insights-table-graph').locator('.insights-label')
        this.addEntityButton = page.getByTestId('add-action-event-button')
        this.firstEntity = page.getByTestId('trend-element-subject-0')
        this.secondEntity = page.getByTestId('trend-element-subject-1')
    }

    async goToNew(insightType?: InsightType): Promise<InsightPage> {
        await this.page.goto(urls.savedInsights())
        await this.page.getByTestId('saved-insights-new-insight-dropdown').click()
        await this.page.locator(`[data-attr-insight-type="${insightType || 'TRENDS'}"]`).click()
        return this
    }

    async createNew(insightType?: InsightType, insightName?: string): Promise<InsightPage> {
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
    async withReload(callback: () => Promise<void>): Promise<void> {
        await callback()
        await this.page.reload()
        await callback()
    }

    /*
     * Metadata
     */
    async editName(insightName: string = randomString('insight')): Promise<void> {
        await this.topBarName.getByRole('button').click()
        await this.topBarName.getByRole('textbox').fill(insightName)
        await this.topBarName.getByRole('button').getByText('Save').click()
    }
}
