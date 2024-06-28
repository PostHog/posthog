import { Locator, Page } from '@playwright/test'

export class Toast {
    readonly page: Page
    readonly container: Locator
    readonly undoButton: Locator

    constructor(page: Page) {
        this.page = page

        this.container = page.locator('.Toastify')
        this.undoButton = this.container.getByRole('button', { name: 'Undo' })
    }

    async undo(): Promise<void> {
        await this.undoButton.click()
    }
}
