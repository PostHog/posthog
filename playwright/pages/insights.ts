import { Locator, Page } from '@playwright/test'

import { urls } from 'scenes/urls'

export class InsightsPage {
    readonly page: Page
    readonly saveInsightButton: Locator
    readonly editNameButton: Locator
    readonly editNameInput: Locator
    readonly editNameSaveButton: Locator

    constructor(page: Page) {
        this.page = page
        this.saveInsightButton = page.getByRole('button', { name: 'Save' })
        this.editNameButton = page
            .getByRole('heading', { name: 'Pageview count Edit' })
            .getByRole('button', { name: 'Edit' })
        this.editNameInput = page.getByPlaceholder('Pageview count')
        this.editNameSaveButton = page
            .getByRole('heading', { name: 'Pageview count Cancel Save' })
            .getByRole('button', { name: 'Save' })
    }

    async goto(): Promise<void> {
        await this.page.goto(urls.insightNew())
    }

    /** Creates a new insight and returns it's dashboardItemId */
    async createInsight(name: string): Promise<string> {
        await this.goto()

        await this.editNameButton.click()
        await this.editNameInput.fill(name)
        await this.editNameSaveButton.click()
        await this.saveInsightButton.click()

        const dashboardItemId = this.page.url().split('/').pop()
        return dashboardItemId
    }
}
