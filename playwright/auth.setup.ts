import { test as setup } from '@playwright/test'
import { urls } from 'scenes/urls'
import {mkdirSync} from "node:fs";
import { dirname, resolve } from 'node:path'

const authFile = resolve('playwright/.auth/user.json')
mkdirSync(dirname(authFile), { recursive: true })

setup('authenticate', async ({ page }) => {
    // perform authentication steps
    await page.goto(urls.login())
    await page.getByPlaceholder('email@yourcompany.com').fill('test@posthog.com')
    await page.getByPlaceholder('••••••••••').fill('12345678')
    await page.getByRole('button', { name: 'Log in' }).click()

    // wait for login to succeed / cookies
    await page.waitForURL(urls.projectHomepage())

    // store auth state
    await page.context().storageState({ path: authFile })
})