import { Locator, Page, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { randomString } from '../utils'

export class DashboardPage {
    readonly page: Page

    readonly topBarName: Locator
    readonly items: Locator
    readonly insightCards: Locator
    readonly textCards: Locator
    readonly dateFilter: Locator
    readonly overridesBanner: Locator
    readonly variableButtons: Locator

    constructor(page: Page) {
        this.page = page

        this.topBarName = page.getByTestId('top-bar-name')
        this.items = page.locator('.dashboard-items-wrapper')
        this.insightCards = page.locator('.InsightCard')
        this.textCards = page.getByTestId('text-card')
        this.dateFilter = page.getByTestId('date-filter')
        this.overridesBanner = page.getByText('You are viewing this dashboard with filter overrides.')
        this.variableButtons = page.locator('.DataVizVariable_Button')
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

    async createFromTemplate(): Promise<DashboardPage> {
        await this.page.goto(urls.dashboards())
        await this.page.getByTestId('new-dashboard').click()

        const modal = this.page.locator('.LemonModal').filter({ hasText: 'Create a dashboard' })
        await expect(modal).toBeVisible()

        const templateOption = this.page.getByTestId('create-dashboard-from-template').first()
        await expect(templateOption).toBeVisible()
        await templateOption.click()

        await expect(this.page).toHaveURL(/\/dashboard\/\d+/)
        return this
    }

    async addInsightToNewDashboard(insightName?: string): Promise<void> {
        await this.page.getByRole('button', { name: 'Add insight' }).first().click()
        const row = insightName
            ? this.page.locator('.LemonModal .LemonTable tbody tr').filter({ hasText: insightName }).first()
            : this.page.locator('.LemonModal .LemonTable tbody tr').first()
        await row.click()
        await this.page.getByRole('button', { name: 'Close' }).click()
    }

    async addTextCard(text: string): Promise<void> {
        await this.page.getByTestId('add-text-tile-to-dashboard').click()

        const modal = this.page.locator('.LemonModal')
        await expect(modal).toBeVisible()

        const textArea = modal.locator('textarea')
        await expect(textArea).toBeVisible()
        await textArea.fill(text)
        await this.page.getByTestId('save-new-text-tile').click()

        await expect(this.textCards.filter({ hasText: text })).toBeVisible()
    }

    async addToNewDashboardFromInsightPage(): Promise<void> {
        await this.openInfoPanel()
        const addButton = this.page.getByTestId('insight-add-to-dashboard-button')
        await expect(addButton).toBeVisible()
        await addButton.click()

        const modal = this.page.locator('.LemonModal').filter({ hasText: 'Add to dashboard' })
        await expect(modal).toBeVisible()

        await modal.getByRole('button', { name: 'Add to a new dashboard' }).click()
        await this.page.getByTestId('create-dashboard-blank').click()

        // After creating a new dashboard from the insight page, the app either:
        // 1. Navigates directly to the dashboard (when _dashboardToNavigateTo is set), OR
        // 2. Shows a toast "Insight added to dashboard" and stays on the insight page
        // Wait for either signal to confirm the async API call has completed.
        await expect(this.page.getByText('Insight added to dashboard').or(this.insightCards)).toBeVisible({
            timeout: 30000,
        })
    }

    async openInfoPanel(): Promise<void> {
        await this.page.getByTestId('info-actions-panel').click()
    }

    async duplicate(): Promise<void> {
        await this.openInfoPanel()
        await this.page.getByTestId('dashboard-duplicate-button').click()

        const modal = this.page.locator('.LemonModal').filter({ hasText: 'Duplicate dashboard' })
        await expect(modal).toBeVisible()
        await this.page.getByTestId('dashboard-submit-and-go').click()

        await expect(this.page).toHaveURL(/\/dashboard\//)
    }

    async deleteDashboard(): Promise<void> {
        await this.openInfoPanel()
        await this.page.getByRole('button', { name: 'Delete dashboard' }).click()

        const modal = this.page.locator('.LemonModal').filter({ hasText: 'Delete dashboard' })
        await expect(modal).toBeVisible()
        await this.page.getByTestId('dashboard-delete-submit').click()
    }

    async setDateFilter(option: string): Promise<void> {
        const dataAttr = `date-filter-${option.toLowerCase().replace(/\s+/g, '-')}`
        await this.dateFilter.click()
        await this.page.getByTestId(dataAttr).click()
        await expect(this.dateFilter).toContainText(option)
    }

    async setVariable(name: string, value: string | number): Promise<void> {
        const field = this.page.locator('.Field').filter({ hasText: name })
        await field.locator('.DataVizVariable_Button').click()

        const popover = this.page.locator('.DataVizVariable_Popover')
        await expect(popover).toBeVisible()

        const input = popover.locator('input')
        await input.fill(String(value))
        await popover.getByRole('button', { name: 'Update' }).click()

        await expect(popover).not.toBeVisible()
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
        const count = await this.insightCards.count()

        for (let i = 0; i < count; i++) {
            const card = this.insightCards.nth(i)
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
        const card = this.insightCards.first()
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
