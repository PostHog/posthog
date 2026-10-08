import { Page, expect } from '@playwright/test'

export class LoginPage {
    constructor(private readonly page: Page) {}

    // A browser that logged in before opens the login page on the recent logins list, which hides the form
    async openAccountForm(): Promise<void> {
        const email = this.page.locator('[data-attr=login-email]')
        const useAnotherAccount = this.page.locator('[data-attr=login-use-another-account]')
        await expect(email.or(useAnotherAccount).first()).toBeVisible()
        if (await useAnotherAccount.isVisible()) {
            await useAnotherAccount.click()
        }
    }

    async enterUsername(username: string): Promise<void> {
        await this.openAccountForm()
        await this.page.locator('[data-attr=login-email]').fill(username)
    }

    async enterPassword(password: string): Promise<void> {
        await this.page.locator('[data-attr=password]').fill(password)
    }

    async clickLogin(): Promise<void> {
        await this.page.locator('[type=submit]').click()
    }
}
