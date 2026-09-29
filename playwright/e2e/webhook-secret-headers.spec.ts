import { Page } from '@playwright/test'

import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

const TEMPLATE_ID = 'template-webhook-secret-headers-e2e'
const SECRET_HEADER_VALUE = 'Bearer e2e-secret-headers-token-0000'
const MASKED_MESSAGE = 'This value is secret and is not displayed here.'
const TRIGGER_NODE_ID = 'trigger_node'
const WEBHOOK_NODE_ID = 'webhook_node'
const EXIT_NODE_ID = 'exit_node'

// The destination editor and the workflow builder render a template's inputs through the same
// component, so a `secret: true` dictionary input (the webhook template's "Secret headers") is the
// one place a person can put a credential header. Nothing below the browser proves that both
// editors let a person enter one, save it, and read it back masked instead of in plaintext, or that
// the marker the editor sends on a later save keeps the stored secret instead of wiping it.
function buildWorkflowWithWebhookStep(): Record<string, any> {
    return {
        name: `Webhook secret headers ${Date.now()}`,
        actions: [
            {
                id: TRIGGER_NODE_ID,
                type: 'trigger',
                name: 'Trigger',
                description: 'Triggered by an event',
                created_at: 0,
                updated_at: 0,
                config: {
                    type: 'event',
                    filters: { events: [{ id: '$pageview', type: 'events' }] },
                },
            },
            {
                id: WEBHOOK_NODE_ID,
                type: 'function',
                name: 'Webhook',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: TEMPLATE_ID,
                    inputs: {},
                },
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

async function createWorkflowViaApi(page: Page, teamId: number): Promise<string> {
    return await page.evaluate(
        async ({ teamId, payload }) => {
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
            const response = await fetch(`/api/environments/${teamId}/hog_flows/`, {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': decodeURIComponent(csrfToken),
                },
                body: JSON.stringify(payload),
            })
            if (!response.ok) {
                throw new Error(`hog_flows POST failed: ${response.status} ${await response.text()}`)
            }
            const data = await response.json()
            return data.id as string
        },
        { teamId, payload: buildWorkflowWithWebhookStep() }
    )
}

async function addSecretHeader(page: Page): Promise<void> {
    // The label renders as a button whose accessible name includes the optional marker.
    await expect(page.getByRole('button', { name: 'Secret headers (optional)' })).toBeVisible({ timeout: 60000 })
    await page.getByRole('button', { name: 'Add entry' }).click()
    await page.getByPlaceholder('Key').fill('Authorization')
    await page.getByPlaceholder('Value').fill(SECRET_HEADER_VALUE)
}

async function expectSecretHeaderMasked(page: Page): Promise<void> {
    await expect(page.getByText(MASKED_MESSAGE)).toBeVisible({ timeout: 15000 })
    await expect(page.getByPlaceholder('Value')).toHaveCount(0)
    await expect(page.getByText(SECRET_HEADER_VALUE)).toHaveCount(0)
    const inputValues = await page
        .locator('input')
        .evaluateAll((inputs) => inputs.map((input) => (input as HTMLInputElement).value))
    expect(inputValues).not.toContain(SECRET_HEADER_VALUE)
}

test.describe('Webhook secret headers', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(180 * 1000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
        })
        // Playwright CI doesn't run sync_hog_function_templates, so the templates table is empty.
        // A dedicated id keeps the seed from being skipped on a database that already holds the
        // real `template-webhook`, and one dictionary input keeps the field locators unambiguous.
        await playwrightSetup.seedHogFunctionTemplate({
            template_id: TEMPLATE_ID,
            name: 'Webhook with secret headers (e2e)',
            status: 'stable',
            template_type: 'destination',
            inputs_schema: [
                {
                    key: 'url',
                    type: 'string',
                    label: 'Webhook URL',
                    required: false,
                    default: 'https://example.com/hooks',
                    description: 'The URL to send the request to.',
                },
                {
                    key: 'secret_headers',
                    type: 'dictionary',
                    label: 'Secret headers',
                    secret: true,
                    required: false,
                    templating: false,
                    description: 'HTTP headers that hold a credential, such as an API token.',
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('a secret header entered in the destination editor is stored encrypted and read back masked', async ({
        page,
    }) => {
        await test.step('create a destination from the template with a secret header', async () => {
            await page.goto(`/functions/new/${TEMPLATE_ID}`)
            await addSecretHeader(page)
            // The button reads "Create & enable" and is rendered in the header and below the form.
            await page
                .getByRole('button', { name: /^Create/ })
                .first()
                .click()
            await page.waitForURL(/\/functions\/(?!new\/)[^/?#]+/, { timeout: 30000 })
        })

        await test.step('the saved destination shows the secret as masked', async () => {
            await page.reload()
            await expectSecretHeaderMasked(page)
        })

        await test.step('saving again without retyping the secret keeps it', async () => {
            await page.getByRole('switch', { name: 'Enable destination' }).click()
            await page.getByRole('button', { name: /^Save/ }).first().click()
            await expect(page.getByRole('button', { name: /^Save/ }).first()).toBeDisabled({ timeout: 15000 })
            await page.reload()
            await expectSecretHeaderMasked(page)
        })
    })

    test('a secret header entered in the workflow builder is stored encrypted and read back masked', async ({
        page,
    }) => {
        const workflowId = await createWorkflowViaApi(page, workspace!.team_id)

        await test.step('open the webhook step and add a secret header', async () => {
            await page.goto(`/workflows/${workflowId}/workflow`)
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await addSecretHeader(page)
        })

        await test.step('save the workflow', async () => {
            await page.getByTestId('workflow-save').click()
            await expect(page.getByTestId('workflow-save')).toBeDisabled({ timeout: 15000 })
        })

        await test.step('the saved step shows the secret as masked', async () => {
            await page.reload()
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${WEBHOOK_NODE_ID}"]`).click()
            await expectSecretHeaderMasked(page)
        })
    })
})
