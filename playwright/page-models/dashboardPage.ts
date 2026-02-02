import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { randomString } from '../utils'

export class DashboardPage {
    readonly page: Page

    readonly topBarName: Locator
    readonly items: Locator

    constructor(page: Page) {
        this.page = page

        this.topBarName = page.getByTestId('top-bar-name')
        this.items = page.locator('.dashboard-items-wrapper')
    }

    async createNew(dashboardName: string = randomString('dashboard')): Promise<DashboardPage> {
        await this.page.goto(urls.dashboards())
        await this.page.getByTestId('new-dashboard').click()
        await this.page.getByTestId('create-dashboard-blank').click()
        await expect(this.page.locator('.dashboard')).toBeVisible()

        await this.editName(dashboardName)
        return this
    }

    async addInsightToNewDashboard(): Promise<void> {
        // Dismiss Quick start popover if visible
        const minimizeButton = this.page.getByText('Minimize')
        if (await minimizeButton.isVisible({ timeout: 2000 }).catch(() => false)) {
            await minimizeButton.click()
        }

        await this.page.getByTestId('info-actions-panel').click()
        await this.page.getByTestId('insight-add-to-dashboard-button').click()
        await this.page.locator('.LemonModal').getByText('Add to a new dashboard').click()
        await this.page.getByTestId('create-dashboard-blank').click()
        await expect(this.items).toBeVisible()
    }

    async withReload(callback: () => Promise<void>, beforeFn?: () => Promise<void>): Promise<void> {
        await beforeFn?.()
        await callback()
        await this.page.reload({ waitUntil: 'networkidle' })
        await callback()
    }

    async editName(dashboardName: string = randomString('dashboard')): Promise<void> {
        await this.topBarName.getByRole('button').click()
        await this.topBarName.getByRole('textbox').fill(dashboardName)
        await this.topBarName.getByRole('button').getByText('Save').click()
    }

    async renameFirstTile(newTileName: string): Promise<void> {
        await this.page.locator('.CardMeta').getByTestId('more-button').click()
        await this.page.locator('.Popover').getByText('Rename').click()
        await this.page.locator('.LemonModal').getByTestId('insight-name').fill(newTileName)
        await this.page.locator('.LemonModal').getByText('Submit').click()
    }

    async removeFirstTile(): Promise<void> {
        await this.page.locator('.CardMeta').getByTestId('more-button').click()
        await this.page.locator('.Popover').getByText('Remove from dashboard').click()
    }

    async duplicateFirstTile(): Promise<void> {
        await this.page.locator('.CardMeta').getByTestId('more-button').click()
        await this.page.locator('.Popover').getByText('Duplicate').click()
    }
}
