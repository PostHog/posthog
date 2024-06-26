import { Locator, Page } from '@playwright/test'

export class ToastObject {
    readonly page: Page
    readonly container: Locator

    constructor(page: Page) {
        this.page = page

        this.container = page.locator('.Toastify')
    }
}
