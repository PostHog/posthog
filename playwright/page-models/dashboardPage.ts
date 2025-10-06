import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { randomString } from '../utils'

export class DashboardPage {
    readonly page: Page

    readonly topBarName: Locator

    constructor(page: Page) {
        this.page = page

        this.topBarName = page.getByTestId('top-bar-name')
    }

    async createNew(dashboardName: string = randomString('dashboard')): Promise<DashboardPage> {
        await this.page.goto(urls.dashboards())
        await this.page.getByTestId('new-dashboard').click()
        await this.page.getByTestId('create-dashboard-blank').click()
        await expect(this.page.locator('.dashboard')).toBeVisible()

        await this.editName(dashboardName)
        return this
    }

    /** Checks assertions, reloads and checks again. This is useful for asserting both the local state
     * and the backend side state are persisted correctly. */
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
