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

    async createNew(dashboardName?: string): Promise<DashboardPage> {
        await this.page.goto(urls.dashboards())
        await this.page.getByTestId('new-dashboard').click()
        await this.page.getByTestId('create-dashboard-blank').click()
        await expect(this.page.locator('.dashboard')).toBeVisible()
        await this.dismissQuickStartIfVisible()

        if (dashboardName) {
            const textarea = this.page.locator('.scene-title-section textarea')
            await textarea.or(this.page.locator('.scene-title-section')).first().click()
            await textarea.fill(dashboardName)
        }

        return this
    }

    async addInsightToNewDashboard(): Promise<void> {
        const addButton = this.page.getByRole('button', { name: 'Add insight' }).first()
        await addButton.click()
        await this.page.getByTestId('dashboard-insight-action-button').first().click()
        await this.page.getByRole('button', { name: 'Close' }).click()
    }

    async addToNewDashboardFromInsightPage(): Promise<void> {
        await this.page.getByTestId('info-actions-panel').click()
        const addButton = this.page.getByTestId('insight-add-to-dashboard-button')
        await expect(addButton).toBeVisible()
        await addButton.click()

        const modal = this.page.locator('.LemonModal').filter({ hasText: 'Add to dashboard' })
        await expect(modal).toBeVisible()

        await modal.getByRole('button', { name: 'Add to a new dashboard' }).click()
        await this.page.getByTestId('create-dashboard-blank').click()
    }

    async closeSidePanels(): Promise<void> {
        await this.page.keyboard.press('Escape')

        const closePanelX = this.page.locator('.scene-layout__content-panel button:has(svg)').first()
        if (await closePanelX.isVisible({ timeout: 1000 }).catch(() => false)) {
            await closePanelX.click()
        }
    }

    async dismissQuickStartIfVisible(): Promise<void> {
        await this.page.keyboard.press('Escape')
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

    async findCardByTitle(title: string): Promise<Locator> {
        const cards = this.page.locator('.InsightCard')
        const count = await cards.count()

        for (let i = 0; i < count; i++) {
            const card = cards.nth(i)
            await card.scrollIntoViewIfNeeded()
            const titleText = await card
                .locator('[data-attr="insight-card-title"]')
                .textContent({ timeout: 5000 })
                .catch(() => null)

            if (titleText?.includes(title)) {
                return card
            }
        }

        throw new Error(`Could not find InsightCard with title "${title}"`)
    }

    async openFirstTileMenu(): Promise<void> {
        const card = this.page.locator('.InsightCard').first()
        await card.scrollIntoViewIfNeeded()
        await card.hover()
        await card.getByTestId('more-button').click()
    }

    async selectTileMenuOption(option: string): Promise<void> {
        const editLink = this.page
            .locator('.Popover')
            .getByRole(option === 'Edit' ? 'link' : 'button', { name: option })
        await editLink.click()
    }
}
