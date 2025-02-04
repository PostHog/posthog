import {mkdirSync} from "node:fs";
import { dirname, resolve } from 'node:path'

import { test as setup } from '@playwright/test'
import { urls } from 'scenes/urls'

const authFile = resolve('playwright/.auth/user.json')

setup('authenticate', async ({ page }) => {
    mkdirSync(dirname(authFile), { recursive: true }) // Ensure directory exists
    
    // perform authentication steps
    await page.goto(urls.login())
    await page.getByPlaceholder('email@yourcompany.com').fill('test@posthog.com')
    await page.getByPlaceholder('••••••••••').fill('12345678')
    await page.getByRole('button', { name: 'Log in' }).click()

    // wait for login to succeed / cookies
    await page.waitForURL(urls.projectHomepage())

        // Fetch storage state before saving
    const storageState = await page.context().storageState()
    console.log('✅ Storage state captured:', JSON.stringify(storageState, null, 2))

    // store auth state
    await page.context().storageState({ path: authFile })
})