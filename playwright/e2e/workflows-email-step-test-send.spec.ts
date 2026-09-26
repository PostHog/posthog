import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

const TRIGGER_NODE_ID = 'trigger_node'
const EXIT_NODE_ID = 'exit_node'
const EMAIL_NODE_ID = 'email_node'

// Mirrors the `email` input of the built-in template
// (nodejs/src/cdp/templates/_destinations/email/email.template.ts). The editor renders a step's
// config from the template map, so without this the panel shows the not-found fallback and the
// step's own controls never mount.
const EMAIL_INPUTS_SCHEMA = [
    {
        type: 'native_email',
        key: 'email',
        label: 'Email message',
        integration: 'email',
        required: true,
        secret: false,
        templating: 'liquid',
        description: 'The email message to send.',
    },
]

function buildEmailWorkflow(): Record<string, any> {
    return {
        name: `Email step test send ${Date.now()}`,
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
                id: EMAIL_NODE_ID,
                type: 'function_email',
                name: 'Send email',
                description: 'Sends the onboarding email',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-email',
                    inputs: {
                        email: {
                            value: {
                                // The audience recipient a real run would resolve. The test send has
                                // to replace this, which is what the assertion below checks.
                                to: { email: '{{ person.properties.email }}', name: '' },
                                from: { integrationId: 1 },
                                cc: 'team@example.com',
                                bcc: 'archive@example.com',
                                subject: 'Welcome aboard',
                                html: '<p>Hello</p>',
                                text: 'Hello',
                                design: null,
                            },
                            templating: 'liquid',
                        },
                    },
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
            { from: TRIGGER_NODE_ID, to: EMAIL_NODE_ID, type: 'continue' },
            { from: EMAIL_NODE_ID, to: EXIT_NODE_ID, type: 'continue' },
        ],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status: 'draft',
    }
}

test.describe('Workflows email step test send', () => {
    test.setTimeout(90 * 1000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
        // Playwright CI doesn't run sync_hog_function_templates, so the templates table is empty.
        await playwrightSetup.seedHogFunctionTemplate({
            template_id: 'template-email',
            name: 'Email',
            status: 'hidden',
            template_type: 'destination',
            inputs_schema: EMAIL_INPUTS_SCHEMA,
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('sends the step to the typed address only, leaving the workflow audience untouched', async ({ page }) => {
        const teamId = workspace!.team_id
        const workflowId = await page.evaluate(
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
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrfToken) },
                    body: JSON.stringify(payload),
                })
                if (!response.ok) {
                    throw new Error(`hog_flows POST failed: ${response.status} ${await response.text()}`)
                }
                return (await response.json()).id as string
            },
            { teamId, payload: buildEmailWorkflow() }
        )

        // A test send is a real send, so the invocation is stubbed rather than allowed to reach the
        // email worker. The payload it would have sent is what this test is here to check.
        let invocationBody: any = null
        await page.route('**/hog_flows/new/invocations/', async (route) => {
            invocationBody = route.request().postDataJSON()
            await route.fulfill({
                status: 200,
                contentType: 'application/json',
                body: JSON.stringify({ status: 'success', nextActionId: null, logs: [] }),
            })
        })

        await test.step('open the workflow editor and select the email step', async () => {
            await page.goto(`/workflows/${workflowId}/workflow`)
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${EMAIL_NODE_ID}"]`).click()
            await expect(page.getByText('Template not found!')).toHaveCount(0)
            await expect(page.getByTestId('workflow-step-open-test-email')).toBeVisible({ timeout: 15000 })
        })

        await test.step('name a recipient and send', async () => {
            await page.getByTestId('workflow-step-open-test-email').click()
            const recipient = page.getByTestId('workflow-step-test-email-recipient')
            await expect(recipient).toBeVisible()
            await recipient.fill('tester@example.com')
            await page.getByTestId('workflow-step-send-test-email').click()
        })

        await test.step('the send carries the typed recipient and only the email step', async () => {
            await expect.poll(() => invocationBody, { timeout: 15000 }).not.toBeNull()

            expect(invocationBody.mock_async_functions).toBe(false)
            expect(invocationBody.current_action_id).toBe('send_test_email')

            const actions = invocationBody.configuration.actions
            expect(actions.map((action: any) => action.type)).toEqual(['trigger', 'function_email', 'exit'])

            const emailAction = actions.find((action: any) => action.type === 'function_email')
            expect(emailAction.config.inputs.email.value).toMatchObject({
                to: { email: 'tester@example.com', name: '' },
                cc: '',
                bcc: '',
                subject: 'Welcome aboard',
            })
        })

        await test.step('the modal closes once the send succeeds', async () => {
            await expect(page.getByTestId('workflow-step-test-email-recipient')).toBeHidden()
        })
    })
})
