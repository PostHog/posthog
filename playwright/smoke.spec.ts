import { test, expect } from '@playwright/test'

test('test', async ({ page }) => {
    await page.goto('http://localhost:8080/login?next=/')
    await page.getByPlaceholder('email@yourcompany.com').click()
    await page.getByPlaceholder('email@yourcompany.com').fill('test@posthog.com')
    await page.getByRole('button', { name: 'Log in' }).click()
    await page.getByPlaceholder('••••••••••').fill('12345678')
    await page.getByRole('button', { name: 'Log in' }).click()
    await page.getByRole('link', { name: 'Product analytics' }).click()
    await page
        .locator(
            '.TopBar3000__actions > .LemonButtonWithSideAction > .LemonButtonWithSideAction__side-button > .LemonButton'
        )
        .click()
    await page.getByRole('link', { name: 'Trends Visualize and break' }).click()
    await page.getByRole('button', { name: 'Add graph series' }).click()
    await page.getByRole('button', { name: 'Save' }).click()
})
