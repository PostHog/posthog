import { Page } from '@playwright/test'

import { expect } from '../utils/playwright-test-base'

export class CohortPage {
    constructor(private readonly page: Page) {}

    async createCohort(name: string): Promise<void> {
        await this.page.click('[data-attr="new-cohort"]')
        await this.page.click('[data-attr="cohort-selector-field-value"]')
        await this.page.click('[data-attr="cohort-personPropertyBehavioral-have_property-type"]')
        await this.page.click('[data-attr="cohort-taxonomic-field-key"]')

        await this.page.locator('[data-attr=prop-filter-person_properties-0]').click()
        await this.page.locator('[data-attr=prop-val]').type('true')

        await this.page.click('[data-attr="cohort-name"]')

        await this.page.fill('[data-attr="cohort-name"]', name)
        await this.page.click('[data-attr="save-cohort"]')

        await expect(this.page.locator('[data-attr=success-toast]')).toHaveText(/Cohort saved/)
        await this.page.locator('[data-attr="toast-close-button"]').click()
    }
}
