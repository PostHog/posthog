import { randomString } from '../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

test.describe('Personal API keys', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('key created in the UI authorizes the API and stops working after deletion', async ({ page, request }) => {
        const label = randomString('e2e-key')
        let apiKey = ''

        await test.step('create a key with the all-access preset', async () => {
            await page.goto('/settings/user-api-keys')
            await page.getByRole('button', { name: 'Create personal API key' }).click()
            await page.getByPlaceholder('For example "Reports bot" or "Zapier"').fill(label)
            await page.getByRole('button', { name: 'All access', exact: true }).click()
            await page.getByText('Select preset').click()
            await page.locator('.Popover__content').getByText('All access').click()
            await page.getByRole('button', { name: 'Create key' }).click()
        })

        await test.step('capture the one-time key value', async () => {
            const dialog = page.locator('.LemonModal').filter({ hasText: 'Personal API key ready' })
            await expect(dialog).toBeVisible()
            const snippet = (await dialog.locator('code').textContent()) ?? ''
            apiKey = snippet.match(/phx_\w+/)?.[0] ?? ''
            expect(apiKey).toMatch(/^phx_/)
            await page.keyboard.press('Escape')
            await expect(dialog).not.toBeVisible()
        })

        await test.step('the key authorizes an API request', async () => {
            const resp = await request.get('/api/users/@me/', {
                headers: { Authorization: `Bearer ${apiKey}` },
            })
            expect(resp.status()).toBe(200)
            expect((await resp.json()).email).toBe(workspace!.user_email)
        })

        await test.step('delete the key via the row menu', async () => {
            const row = page.locator('tr', { hasText: label })
            await row.locator('td').last().getByRole('button').click()
            await page.getByRole('menuitem', { name: 'Delete' }).click()
            await page.getByRole('button', { name: 'Permanently delete' }).click()
            await expect(row).not.toBeVisible()
        })

        await test.step('the deleted key no longer authorizes', async () => {
            const resp = await request.get('/api/users/@me/', {
                headers: { Authorization: `Bearer ${apiKey}` },
            })
            expect(resp.status()).toBe(401)
        })
    })
})
