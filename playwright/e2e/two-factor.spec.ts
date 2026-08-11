import { createHmac } from 'crypto'

import { LoginPage } from '../page-models/loginPage'
import { LOGIN_PASSWORD } from '../utils/playwright-test-core'
import { expect, test } from '../utils/workspace-test-base'

function base32Decode(secret: string): Buffer {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
    let bits = 0
    let value = 0
    const bytes: number[] = []
    for (const char of secret.replace(/=+$/, '').toUpperCase()) {
        value = (value << 5) | alphabet.indexOf(char)
        bits += 5
        if (bits >= 8) {
            bytes.push((value >>> (bits - 8)) & 0xff)
            bits -= 8
        }
    }
    return Buffer.from(bytes)
}

function totp(secret: string, atMs: number): string {
    const counter = Buffer.alloc(8)
    counter.writeBigUInt64BE(BigInt(Math.floor(atMs / 1000 / 30)))
    const hmac = createHmac('sha1', base32Decode(secret)).update(counter).digest()
    const offset = hmac[hmac.length - 1] & 0xf
    return String((hmac.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0')
}

test.describe('Two-factor authentication', () => {
    test('login requires a TOTP code once 2FA is enabled', async ({ page, playwrightSetup }) => {
        const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        await playwrightSetup.login(page, workspace)
        let secret = ''

        await test.step('enable TOTP from user settings', async () => {
            await page.goto('/settings/user-profile')
            await page.getByRole('button', { name: 'Setup', exact: true }).click()
            const modal = page.locator('.LemonModal').filter({ hasText: 'authenticator' })
            const secretText = modal.getByText(/^[A-Z2-7]{16,}$/)
            await expect(secretText).toBeVisible()
            secret = (await secretText.textContent()) ?? ''
            await page.locator('[data-attr=token]').fill(totp(secret, Date.now()))
            await page.locator('[data-attr="2fa-setup"]').click()
            await expect(page.locator('[data-attr="2fa-setup"]')).not.toBeVisible({ timeout: 15000 })
        })

        await test.step('log out via the account menu', async () => {
            await page.locator('[data-attr=new-account-menu-button]').click()
            await page.locator('[data-attr=new-account-menu-logout-button]').click()
            await page.waitForURL(/\/login/, { timeout: 15000 })
        })

        await test.step('password login lands on the 2FA challenge instead of the app', async () => {
            const loginPage = new LoginPage(page)
            await loginPage.enterUsername(workspace.user_email)
            await loginPage.enterPassword(LOGIN_PASSWORD)
            await loginPage.clickLogin()
            await expect(page.locator('[data-attr=token]')).toBeVisible({ timeout: 15000 })
        })

        await test.step('a valid TOTP code completes the login', async () => {
            // Use the next 30s window: the current window's code was consumed during
            // setup, and django_otp rejects token reuse within the same window.
            await page.locator('[data-attr=token]').fill(totp(secret, Date.now() + 30_000))
            await page.locator('[data-attr="2fa-login"]').click()
            await page.waitForURL(/\/project\//, { timeout: 30000 })
        })
    })
})
