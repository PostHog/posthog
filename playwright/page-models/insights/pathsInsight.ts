import { Locator, Page, expect } from '@playwright/test'

export class PathsInsight {
    readonly container: Locator

    constructor(page: Page) {
        this.container = page.getByTestId('paths-viz')
    }

    async waitForChart(): Promise<void> {
        await expect(this.container).toBeVisible()
    }
}
