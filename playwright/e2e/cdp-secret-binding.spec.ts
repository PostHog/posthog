import { Locator, Page } from '@playwright/test'

import { LOGIN_PASSWORD } from '../utils/playwright-test-core'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

// A stored secret, and a linked integration's credentials, stay bound to the address they were
// saved for. The backend decides that; these tests cover the part only a browser proves.
//
// Three things live above the API and nothing below this layer exercises them. The destination
// editor must put the refusal on the field the person has to retype, not only in a toast that
// loses which input it meant, and must not leave the rejected URL on screen as though it saved.
// The workflow builder saves leniently, so there the stored secret is dropped rather than refused,
// and the check is that it does not travel to the new address. And a save refused for a stale
// session has to reach the shared re-authentication modal and come back from it, which spans the
// kea error handler, the modal, the login endpoint and the retried save at once.
//
// The templates below carry a real `fetch` call because the backend traces the template code to
// work out which inputs reach a URL. A template whose code never fetches has no URL inputs to
// rebind, so a test seeded against one would pass without the feature being there at all.

const SECRET_TEMPLATE_ID = 'template-secret-binding-e2e'
const INTEGRATION_TEMPLATE_ID = 'template-integration-reauth-e2e'

const ORIGINAL_URL = 'https://example.com/hooks'
const REBOUND_URL = 'https://rebound.example.com/hooks'
const SECRET_HEADER_VALUE = 'Bearer e2e-secret-binding-token-0000'
const RETYPED_HEADER_VALUE = 'Bearer e2e-secret-binding-token-1111'

const REBOUND_ERROR = 'The code or address that receives this secret changed. Enter the secret again.'
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

function fieldError(page: Page, message: string): Locator {
    // The save failure also raises a toast carrying the same sentence. Scoping to the errored field
    // is the point of the check: the person has to know which input to retype.
    return page.locator('.Field--error').filter({ hasText: message })
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

    test('a destination refuses a stored secret once its URL changes, and takes it again when retyped', async ({
        page,
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

        await test.step('changing the URL while keeping the stored secret is refused on the field', async () => {
            await urlInput(page).fill(REBOUND_URL)
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await expect(fieldError(page, REBOUND_ERROR)).toBeVisible({ timeout: 15000 })
        })

        await test.step('the refused URL was not stored', async () => {
            await page.reload()
            await expect(urlInput(page)).toHaveValue(ORIGINAL_URL, { timeout: 30000 })
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible()
        })

        await test.step('retyping the secret lets the same change through', async () => {
            await urlInput(page).fill(REBOUND_URL)
            // The stored entries are not shown behind "Edit", so retyping means entering them again.
            await page.getByRole('button', { name: 'Edit', exact: true }).click()
            await addSecretHeader(page, RETYPED_HEADER_VALUE)
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await expect(fieldError(page, REBOUND_ERROR)).toHaveCount(0, { timeout: 15000 })
            await page.reload()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
        })
    })

    test('a workflow step drops its stored secret once its URL changes', async ({ page }) => {
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
        })

        await test.step('the stored secret does not follow the step to a new URL', async () => {
            await page.reload()
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
            await urlInput(page).fill(REBOUND_URL)
            await page.getByTestId('workflow-save').click()
            await expect(page.getByTestId('workflow-save')).toBeDisabled({ timeout: 15000 })
        })

        await test.step('the step kept the new URL and lost the secret', async () => {
            await page.reload()
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
            await expect(page.getByText(MASKED_MESSAGE)).toHaveCount(0)
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

        await test.step('age the session past the sensitive-action window', async () => {
            const cookies = await page.context().cookies()
            const sessionCookie = cookies.find((cookie) => cookie.name.endsWith('sessionid'))
            expect(sessionCookie, 'session cookie should be set after login').toBeTruthy()
            await playwrightSetup.expireSessionReauth(sessionCookie!.value)
        })

        await test.step('redirecting the linked destination asks for the password again', async () => {
            await page.goto(`/functions/${destination.id}`)
            await expect(urlInput(page)).toHaveValue(ORIGINAL_URL, { timeout: 30000 })
            await urlInput(page).fill(REBOUND_URL)
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await expect(page.getByRole('heading', { name: REAUTH_TITLE })).toBeVisible({ timeout: 15000 })
        })

        await test.step('the save lands once the password is entered', async () => {
            await page.getByTestId('password').fill(LOGIN_PASSWORD)
            await page.getByRole('button', { name: 'Re-authenticate' }).click()
            await expect(page.getByRole('heading', { name: REAUTH_TITLE })).toBeHidden({ timeout: 30000 })
            await page.reload()
            await expect(urlInput(page)).toHaveValue(REBOUND_URL, { timeout: 30000 })
        })
    })
})
