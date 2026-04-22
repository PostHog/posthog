import { Locator, Page } from '@playwright/test'

function escapeRegExp(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export class TaxonomicFilter {
    readonly searchField: Locator
    readonly rows: Locator
    private readonly expandRow: Locator

    constructor(private readonly page: Page) {
        this.searchField = page.getByTestId('taxonomic-filter-searchfield')
        this.rows = page.getByRole('option')
        this.expandRow = page.getByRole('button', { name: 'Show more items' }).first()
    }

    async selectItem(name: string): Promise<void> {
        await this.searchField.waitFor({ state: 'visible' })
        await this.searchField.fill(name)

        const row = this.findRow(name)
        await this.revealIfHidden(row)
        await row.click()
    }

    /** Match either the raw identifier or its human-readable form (e.g. "$browser" → "browser"). */
    private findRow(name: string): Locator {
        const displayName = name.startsWith('$') ? name.slice(1).replace(/_/g, ' ') : name
        const pattern = new RegExp(`${escapeRegExp(name)}|${escapeRegExp(displayName)}`, 'i')
        return this.rows.filter({ hasText: pattern }).first()
    }

    /** The row may be behind a "show N unseen properties" expand-row — click it if needed. */
    private async revealIfHidden(row: Locator): Promise<void> {
        // Wait for either the target row or the expand row to appear (first in DOM order)
        await row.or(this.expandRow).first().waitFor({ state: 'visible' })

        const isVisible = await row.isVisible()

        if (!isVisible) {
            await this.expandRow.click()
            await row.waitFor({ state: 'visible' })
        }
    }

    async selectTab(groupType: string): Promise<void> {
        await this.page.getByTestId(`taxonomic-tab-${groupType}`).last().click()
    }
}
