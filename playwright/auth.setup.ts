import { test as setup, expect } from '@playwright/test'
import { urls } from 'scenes/urls'

const authFile = 'playwright/.auth/user.json'

setup('authenticate', async ({ page }) => {
    // perform authentication steps
    await page.goto(urls.login())
    await page.getByPlaceholder('email@yourcompany.com').fill('test@posthog.com')
    await page.getByPlaceholder('••••••••••').fill('12345678')
    await page.getByRole('button', { name: 'Log in' }).click()

    // wait for cookies
    await page.waitForURL('https://github.com/')

    // store auth state
    await page.context().storageState({ path: authFile })
})
