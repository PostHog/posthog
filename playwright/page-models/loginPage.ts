import { Page } from '@playwright/test'

export class LoginPage {
    constructor(private readonly page: Page) {}

    async enterUsername(username: string): Promise<void> {
        await this.page.locator('[data-attr=login-email]').fill(username)
    }

    async continueWithEmail(): Promise<void> {
        await this.page.locator('[data-attr=login-email-continue]').click()
        await this.page.locator('[data-attr=password]').waitFor({ state: 'visible', timeout: 5000 })
    }

    async enterPassword(password: string): Promise<void> {
        await this.page.locator('[data-attr=password]').fill(password)
    }

    async clickLogin(): Promise<void> {
        await this.page.locator('[type=submit]').click()
    }
}
