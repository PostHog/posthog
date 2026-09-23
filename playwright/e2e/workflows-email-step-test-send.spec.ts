import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

const TRIGGER_NODE_ID = 'trigger_node'
const EXIT_NODE_ID = 'exit_node'
const EMAIL_NODE_ID = 'email_node'

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
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('sends the step to the typed address only, leaving the workflow audience untouched', async ({ page }) => {
        test.setTimeout(90 * 1000)
        const me = await page.request.get('/api/users/@me/')
        expect(me.ok()).toBe(true)
        const teamId: number = (await me.json()).team.id

        const csrfToken = (await page.context().cookies()).find((c) => c.name === 'posthog_csrftoken')?.value
        if (!csrfToken) {
            throw new Error('CSRF cookie missing')
        }
        const response = await page.request.post(`/api/environments/${teamId}/hog_flows/`, {
            data: buildEmailWorkflow(),
            headers: { 'X-CSRFToken': decodeURIComponent(csrfToken) },
        })
        if (!response.ok()) {
            throw new Error(`hog_flows POST failed: ${response.status()} ${await response.text()}`)
        }
        const workflowId: string = (await response.json()).id

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
            await expect(page.getByTestId('workflow-step-open-test-email')).toBeVisible()
        })

        await test.step('name a recipient and send', async () => {
            await page.getByTestId('workflow-step-open-test-email').click()
            const recipient = page.getByTestId('workflow-step-test-email-recipient')
            await expect(recipient).toBeVisible()
            await recipient.fill('tester@example.com')
            await page.getByTestId('workflow-step-send-test-email').click()
        })

        await test.step('the send carries the typed recipient and only the email step', async () => {
            await expect.poll(() => invocationBody).not.toBeNull()

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
