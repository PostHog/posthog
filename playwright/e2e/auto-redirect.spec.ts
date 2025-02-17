import { test, expect } from '../utils/playwright-test-base'
import { Page } from '@playwright/test'

const BASE_URL = 'http://localhost:8000'

const setCookies = async (page: Page, instance: string) => {
    await page.context().addCookies([
        { name: 'ph_current_instance', value: `"${instance}"`, url: BASE_URL },
        { name: 'is-logged-in', value: '1', url: BASE_URL },
    ])
}

test.describe('Redirect to other subdomain if logged in', () => {
    test.beforeEach(async ({ page }) => {
        await page.context().clearCookies()
    })

    test('Redirects to the EU instance', async ({ page, baseURL }) => {
        await page.goto(`${baseURL}/logout`)

        const redirectPath = '/test'
        await page.goto(`${baseURL}/login?next=${redirectPath}`)

        await setCookies(page, 'eu.posthog.com')
        await page.reload()

        const expectedURL = baseURL?.replace('localhost', 'eu.localhost')
        await expect(page).toHaveURL(`${expectedURL}/login?next=${redirectPath}`)
    })

    test('Redirects to the US instance', async ({ page, baseURL }) => {
        await page.goto(`${baseURL}/logout`)

        const redirectPath = '/test'
        await page.goto(`${baseURL}/login?next=${redirectPath}`)

        await setCookies(page, 'us.posthog.com')
        await page.reload()

        const expectedURL = baseURL?.replace('localhost', 'us.localhost')

        await expect(page).toHaveURL(`${expectedURL}/login?next=${redirectPath}`)
    })
})
