import { test as setup } from '@playwright/test'

const LOGIN_USERNAME = process.env.LOGIN_USERNAME || 'test@posthog.com'
const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD || '12345678'

setup('authenticate', async ({ page }) => {
    await page.request.post('/api/login/', {
        data: { email: LOGIN_USERNAME, password: LOGIN_PASSWORD },
    })
    await page.context().storageState({ path: 'playwright/.auth/user.json' })
})
