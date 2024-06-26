import { Locator, Page } from '@playwright/test'
import { urls } from 'scenes/urls'

import { InsightType } from '~/types'

import { randomString } from '../utils'

export class InsightPage {
    readonly page: Page
    readonly saveButton: Locator
    readonly editButton: Locator
    readonly topBarName: Locator

    constructor(page: Page) {
        this.page = page

        this.saveButton = page.getByTestId('insight-save-button')
        this.editButton = page.getByTestId('insight-edit-button')
        this.topBarName = page.getByTestId('top-bar-name')
    }

    async goToNew(insightType?: InsightType): Promise<void> {
        await this.page.goto(urls.savedInsights())
        await this.page.getByTestId('saved-insights-new-insight-dropdown').click()
        await this.page.locator(`[data-attr-insight-type="${insightType || 'TRENDS'}"]`).click()
    }

    async createNew(insightType?: InsightType, insightName?: string): Promise<void> {
        await this.goToNew(insightType)
        await this.editName(insightName)
        await this.save()
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

    async withEdit(callback: () => Promise<void>): Promise<void> {
        await this.edit()
        await callback()
        await this.save()
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
