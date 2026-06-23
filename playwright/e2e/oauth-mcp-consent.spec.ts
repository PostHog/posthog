import { LOGIN_PASSWORD } from '../utils/playwright-test-core'
import { expect, test } from '../utils/workspace-test-base'

const CLIENT_ID = 'e2e_mcp_consent_client_id'
const CODE_CHALLENGE = 'UI2rDDeC_UEA-4FbZQEa6BwaHxrXvWfXUTju4YEJ5xY'

test.describe('OAuth MCP consent', () => {
    test('shows full MCP scope catalog when scope param is omitted', async ({ page }) => {
        await test.step('log in', async () => {
            await page.goto('/login')
            await page.waitForLoadState('networkidle')
            await page.evaluate(
                async ({ email, password }) => {
                    const res = await fetch('/api/login/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email, password }),
                    })
                    if (!res.ok) {
                        throw new Error(`Login failed with status ${res.status}`)
                    }
                },
                { email: 'dev@example.com', password: LOGIN_PASSWORD }
            )
        })

        const authorizeUrl =
            '/oauth/authorize/' +
            `?client_id=${CLIENT_ID}` +
            '&redirect_uri=https%3A%2F%2Fexample.com%2Fcallback' +
            '&response_type=code' +
            `&code_challenge=${CODE_CHALLENGE}` +
            '&code_challenge_method=S256' +
            '&resource=https%3A%2F%2Fmcp.posthog.com%2Fmcp'

        await test.step('load consent page', async () => {
            await page.goto(authorizeUrl)
            await expect(page.getByRole('button', { name: 'Authorize E2E MCP Consent Test App' })).toBeVisible({
                timeout: 30_000,
            })
            await expect(page.getByText('Loading permissions...')).toBeHidden({ timeout: 60_000 })
        })

        await test.step('assert server-preloaded MCP scopes', async () => {
            await expect(page.getByText('Showing all permissions supported by this resource')).toBeVisible()
            await expect(page.getByText('Limited permission list')).toBeHidden()
            await expect(page.getByText(/access to notebooks/i)).toBeVisible()
        })
    })
})
