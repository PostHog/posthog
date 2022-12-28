import { Page } from '@playwright/test'

export class AuthPage {
    readonly page: Page

    constructor(page: Page) {
        this.page = page
    }

    async login(): Promise<void> {
        await this.page.goto('/')
        await this.page.getByTestId('login-email').fill('test@posthog.com')
        await this.page.getByRole('button', { name: 'Login' }).click()
        await this.page.getByTestId('password').fill('12345678')
        await this.page.getByRole('button', { name: 'Login' }).click()
        await this.page.locator('.page-title').waitFor()
    }
}
