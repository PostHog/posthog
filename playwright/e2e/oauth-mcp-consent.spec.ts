import { expect, test, testWithWorkspace } from '../utils/workspace-test-base'

const CLIENT_ID = 'e2e_mcp_consent_client_id'
const CODE_CHALLENGE = 'UI2rDDeC_UEA-4FbZQEa6BwaHxrXvWfXUTju4YEJ5xY'

testWithWorkspace.describe('OAuth MCP consent', () => {
    testWithWorkspace(
        'shows full MCP scope catalog when scope param is omitted',
        async ({ page, workspace, playwrightSetup }) => {
            await test.step('seed OAuth app and log in', async () => {
                await playwrightSetup.callSetupEndpoint('oauth_application', {})
                await playwrightSetup.login(page, workspace)
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
            })

            await test.step('assert server-preloaded MCP scopes', async () => {
                await expect(page.getByText('Showing all permissions supported by this resource')).toBeVisible()
                // notebook scopes are absent from the old static fallback, so their
                // presence proves the server derived the full catalog.
                await expect(page.getByText(/access to notebooks/i)).toBeVisible()
            })
        }
    )
})
