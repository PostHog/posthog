import { Locator, Page, expect } from '@playwright/test'

import { TableHelper } from '../utils/table-helper'

export class PersonsPage {
    readonly page: Page

    readonly table: Locator
    readonly searchInput: Locator
    readonly tabs: Locator
    readonly propertiesTab: Locator
    readonly eventsTab: Locator
    readonly cohortsTab: Locator
    readonly addPropertyButton: Locator
    readonly personDistinctId: Locator
    readonly splitIdsButton: Locator
    readonly deletePersonButton: Locator

    constructor(page: Page) {
        this.page = page

        this.table = page.getByTestId('persons-table')
        this.searchInput = page.getByTestId('persons-search')
        this.tabs = page.getByTestId('persons-tabs')
        this.propertiesTab = page.getByTestId('persons-properties-tab')
        this.eventsTab = page.getByTestId('persons-events-tab')
        this.cohortsTab = page.getByTestId('persons-cohorts-tab')
        this.addPropertyButton = page.getByTestId('add-prop-button')
        this.personDistinctId = page.getByTestId('person-distinct-id')
        this.splitIdsButton = page.locator('[data-attr="merge-person-button"]')
        this.deletePersonButton = page.locator('[data-attr="delete-person"]').first()
    }

    detailTable(): TableHelper {
        return new TableHelper(this.page.locator('table').first())
    }

    async goToList(): Promise<void> {
        await this.page.goto('/persons')
        await expect(this.table).toBeVisible()
    }

    async searchFor(query: string, expectedCount: number = 1): Promise<void> {
        await this.searchInput.fill(query)
        await expect(this.table.getByRole('link')).toHaveCount(expectedCount)
    }

    async clickFirstPerson(): Promise<void> {
        const link = this.table.getByRole('link').first()
        const href = await link.getAttribute('href')
        await this.page.goto(href!, { waitUntil: 'domcontentloaded' })
        await expect(this.tabs).toBeVisible({ timeout: 15_000 })
    }

    async clickNthPerson(n: number = 0): Promise<void> {
        const link = this.table.getByRole('link').nth(n)
        const href = await link.getAttribute('href')
        await this.page.goto(href!, { waitUntil: 'domcontentloaded' })
        await expect(this.tabs).toBeVisible({ timeout: 15_000 })
    }

    async goToPropertiesTab(): Promise<void> {
        await this.propertiesTab.click()
        await expect(this.addPropertyButton).toBeVisible()
    }

    async goToEventsTab(): Promise<void> {
        await this.eventsTab.click()
        await expect(this.page.getByText('Select events')).toBeVisible()
    }

    async addProperty(key: string, value: string): Promise<void> {
        await this.addPropertyButton.click()
        await this.page.locator('#propertyKey').fill(key)
        await this.page.locator('#propertyValue').fill(value)
        await this.page.getByRole('button', { name: 'Save' }).click()
        await expect(this.page.getByText('Person property added')).toBeVisible()
    }

    async deleteProperty(key: string): Promise<void> {
        const propRow = this.page.locator('tr').filter({ hasText: key })
        await propRow.getByTestId('delete-prop-button').click()
        await expect(this.page.getByText('Are you sure you want to delete property')).toBeVisible()
        await this.page.getByRole('button', { name: 'Delete' }).click()
        await expect(this.page.getByText('Person property deleted')).toBeVisible()
    }

    async openSplitIdsModal(): Promise<void> {
        await this.splitIdsButton.click()
        await expect(this.page.getByText('This will split all Distinct IDs')).toBeVisible()
    }

    async openDeleteModal(): Promise<void> {
        await this.deletePersonButton.click()
        await expect(this.page.getByText('Are you sure you want to delete')).toBeVisible()
    }

    async cancelDeleteModal(): Promise<void> {
        await this.page.locator('[data-attr="delete-person-cancel"]').click()
        await expect(this.page.getByText('Are you sure you want to delete')).not.toBeVisible()
    }
}
