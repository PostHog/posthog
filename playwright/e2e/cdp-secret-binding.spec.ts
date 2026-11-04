import { Locator, Page } from '@playwright/test'

import { LOGIN_PASSWORD } from '../utils/playwright-test-core'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

// A stored secret, and a linked integration's credentials, move to a new address only from a
// recent login. The backend decides that; these tests cover the part only a browser proves.
//
// A save refused for a stale session has to reach the shared re-authentication modal and come back
// from it, which spans the kea error handler, the modal, the login endpoint and the retried save
// at once. That path has to work from both editors, because the workflow builder saves leniently
// and could swallow the refusal, and the destination editor must leave the credential stored
// rather than blank it after the retry.

const SECRET_TEMPLATE_ID = 'template-secret-binding-e2e'
const INTEGRATION_TEMPLATE_ID = 'template-integration-reauth-e2e'

const ORIGINAL_URL = 'https://example.com/hooks'
const REBOUND_URL = 'https://rebound.example.com/hooks'
const SECRET_HEADER_VALUE = 'Bearer e2e-secret-binding-token-0000'

const MASKED_MESSAGE = 'This value is secret and is not displayed here.'
const REAUTH_TITLE = 'Re-authenticate for security'

const TRIGGER_NODE_ID = 'trigger_node'
const WEBHOOK_NODE_ID = 'webhook_node'
const EXIT_NODE_ID = 'exit_node'

function urlInput(page: Page): Locator {
    // The label is a plain LemonLabel with no `htmlFor`, so the input has no accessible name to
    // query by. `cyclotron-job-input-<key>` is the handle the inputs component exposes.
    return page.getByTestId('cyclotron-job-input-url').getByRole('textbox')
}

async function reauthenticate(page: Page): Promise<void> {
    await expect(page.getByRole('heading', { name: REAUTH_TITLE })).toBeVisible({ timeout: 15000 })
    await page.getByTestId('password').fill(LOGIN_PASSWORD)
    await page.getByRole('button', { name: 'Re-authenticate' }).click()
    await expect(page.getByRole('heading', { name: REAUTH_TITLE })).toBeHidden({ timeout: 30000 })
}

async function expireSession(
    page: Page,
    playwrightSetup: { expireSessionReauth: (key: string) => Promise<void> }
): Promise<void> {
    const cookies = await page.context().cookies()
    const sessionCookie = cookies.find((cookie) => cookie.name.endsWith('sessionid'))
    expect(sessionCookie, 'session cookie should be set after login').toBeTruthy()
    await playwrightSetup.expireSessionReauth(sessionCookie!.value)
}

async function addSecretHeader(page: Page, value: string): Promise<void> {
    await expect(page.getByRole('button', { name: 'Secret headers (optional)' })).toBeVisible({ timeout: 60000 })
    await page.getByRole('button', { name: 'Add entry' }).click()
    await page.getByPlaceholder('Key').fill('Authorization')
    await page.getByPlaceholder('Value').fill(value)
}

async function postJson(page: Page, path: string, payload: Record<string, any>): Promise<any> {
    return await page.evaluate(
        async ({ path, payload }) => {
            const csrfToken =
                document.cookie
                    .split(';')
                    .map((c) => c.trim())
                    .find((c) => c.startsWith('posthog_csrftoken='))
                    ?.split('=')
                    .slice(1)
                    .join('=') || ''
            if (!csrfToken) {
                throw new Error('CSRF cookie missing')
            }
            const response = await fetch(path, {
                method: 'POST',
                credentials: 'include',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrfToken) },
                body: JSON.stringify(payload),
            })
            if (!response.ok) {
                throw new Error(`POST ${path} failed: ${response.status} ${await response.text()}`)
            }
            return await response.json()
        },
        { path, payload }
    )
}

function workflowWithWebhookStep(): Record<string, any> {
    return {
        name: `Secret binding ${Date.now()}`,
        actions: [
            {
                id: TRIGGER_NODE_ID,
                type: 'trigger',
                name: 'Trigger',
                description: 'Triggered by an event',
                created_at: 0,
                updated_at: 0,
                config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
            },
            {
                id: WEBHOOK_NODE_ID,
                type: 'function',
                name: 'Webhook',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: { template_id: SECRET_TEMPLATE_ID, inputs: { url: { value: ORIGINAL_URL } } },
            },
            {
                id: EXIT_NODE_ID,
                type: 'exit',
                name: 'Exit',
                description: 'Default exit',
                created_at: 0,
                updated_at: 0,
                config: { reason: 'Default exit' },
            },
        ],
        edges: [
            { from: TRIGGER_NODE_ID, to: WEBHOOK_NODE_ID, type: 'continue' },
            { from: WEBHOOK_NODE_ID, to: EXIT_NODE_ID, type: 'continue' },
        ],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status: 'draft',
    }
}

test.describe('CDP secret binding', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(180 * 1000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })

        await playwrightSetup.seedHogFunctionTemplate({
            template_id: SECRET_TEMPLATE_ID,
            name: 'Webhook with a bound secret (e2e)',
            status: 'stable',
            template_type: 'destination',
            code: "fetch(inputs.url, {'headers': inputs.secret_headers});",
            inputs_schema: [
                {
                    key: 'url',
                    type: 'string',
                    label: 'Webhook URL',
                    required: true,
                    default: ORIGINAL_URL,
                    templating: false,
                },
                {
                    key: 'secret_headers',
                    type: 'dictionary',
                    label: 'Secret headers',
                    secret: true,
                    required: false,
                    templating: false,
                },
            ],
        })

        await playwrightSetup.seedHogFunctionTemplate({
            template_id: INTEGRATION_TEMPLATE_ID,
            name: 'Webhook with a linked integration (e2e)',
            status: 'stable',
            template_type: 'destination',
            code: "fetch(inputs.url, {'headers': {'Authorization': inputs.connection.access_token}});",
            inputs_schema: [
                {
                    key: 'url',
                    type: 'string',
                    label: 'Webhook URL',
                    required: true,
                    default: ORIGINAL_URL,
                    templating: false,
                },
                { key: 'connection', type: 'integration', integration: 'slack', label: 'Slack', required: false },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('a destination keeps its stored secret when a re-authenticated save moves it', async ({
        page,
        playwrightSetup,
    }) => {
        await test.step('create a destination with a secret header', async () => {
            await page.goto(`/functions/new/${SECRET_TEMPLATE_ID}`)
            await addSecretHeader(page, SECRET_HEADER_VALUE)
            await page
                .getByRole('button', { name: /^Create/ })
                .first()
                .click()
            await page.waitForURL(/\/functions\/(?!new\/)[^/?#]+/, { timeout: 30000 })
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
        })

        await test.step('changing the URL from a stale session asks for the password', async () => {
            await expireSession(page, playwrightSetup)
            await urlInput(page).fill(REBOUND_URL)
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await reauthenticate(page)
        })

        await test.step('the new URL is stored and the secret is still there', async () => {
            await page.reload()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
            // Blanking the secret here would silently disable the webhook's auth on the next save.
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
        })
    })

    test('a lenient workflow save surfaces the refusal instead of swallowing it', async ({ page, playwrightSetup }) => {
        const workflow = await postJson(
            page,
            `/api/environments/${workspace!.team_id}/hog_flows/`,
            workflowWithWebhookStep()
        )

        await test.step('add a secret header to the webhook step and save', async () => {
            await page.goto(`/workflows/${workflow.id}/workflow`)
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await addSecretHeader(page, SECRET_HEADER_VALUE)
            await page.getByTestId('workflow-save').click()
            await expect(page.getByTestId('workflow-save')).toBeDisabled({ timeout: 15000 })
            // A disabled button does not prove the save landed. Without a stored secret, the next
            // save would carry the secret and the new URL together and rightly need no login.
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
        })

        await test.step('moving the step from a stale session asks for the password', async () => {
            await expireSession(page, playwrightSetup)
            await urlInput(page).fill(REBOUND_URL)
            await page.getByTestId('workflow-save').click()
            await reauthenticate(page)
        })

        await test.step('the step kept the new URL and its secret', async () => {
            await page.reload()
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
        })
    })

    test('linking a destination to an integration from a stale session goes through re-authentication', async ({
        page,
        playwrightSetup,
    }) => {
        const integration = await playwrightSetup.seedIntegration({ team_id: Number(workspace!.team_id) })

        const destination = await postJson(page, `/api/projects/${workspace!.team_id}/hog_functions/`, {
            type: 'destination',
            name: 'Linked destination',
            template_id: INTEGRATION_TEMPLATE_ID,
            hog: "fetch(inputs.url, {'headers': {'Authorization': inputs.connection.access_token}});",
            inputs_schema: [
                { key: 'url', type: 'string', label: 'Webhook URL', required: true, templating: false },
                { key: 'connection', type: 'integration', integration: 'slack', label: 'Slack', required: false },
            ],
            inputs: { url: { value: ORIGINAL_URL }, connection: { value: integration.integration_id } },
        })

        await test.step('redirecting the linked destination asks for the password again', async () => {
            await expireSession(page, playwrightSetup)
            await page.goto(`/functions/${destination.id}`)
            await expect(urlInput(page)).toHaveValue(ORIGINAL_URL, { timeout: 30000 })
            await urlInput(page).fill(REBOUND_URL)
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await reauthenticate(page)
        })

        await test.step('the save lands once the password is entered', async () => {
            await page.reload()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
        })
    })
})
