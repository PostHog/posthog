import { PlaywrightWorkspaceSetupResult, expect, test } from '../utils/workspace-test-base'

const TRIGGER_NODE_ID = 'trigger_node'
const EXIT_NODE_ID = 'exit_node'
const CAPTURE_NODE_ID = 'capture_node'

// `template-posthog-capture` is shipped with `status: 'hidden'` (see
// nodejs/src/cdp/templates/_destinations/posthog_capture/posthog-capture.template.ts).
// The workflow editor loads every template via the authenticated project list and uses the
// resulting map to render each step's config. A previous change excluded hidden templates from
// that list, which made workflows containing this step render "Template not found!" and blocked
// editing or creating them. This test guards against that regression.
function buildWorkflowWithCaptureStep(): Record<string, any> {
    return {
        name: `Hidden template load ${Date.now()}`,
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
                id: CAPTURE_NODE_ID,
                type: 'function',
                name: 'Capture a PostHog event',
                description: '',
                created_at: 0,
                updated_at: 0,
                config: {
                    template_id: 'template-posthog-capture',
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
            { from: TRIGGER_NODE_ID, to: CAPTURE_NODE_ID, type: 'continue' },
            { from: CAPTURE_NODE_ID, to: EXIT_NODE_ID, type: 'continue' },
        ],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status: 'draft',
    }
}

test.describe('Workflows hidden built-in templates load', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(90 * 1000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            no_demo_data: true,
        })
        // Playwright CI doesn't run sync_hog_function_templates, so the templates table is
        // empty. Seed the one this test references with status='hidden' — that's the regression
        // class we want to catch (a server-side filter that strips hidden templates).
        await playwrightSetup.seedHogFunctionTemplate({
            template_id: 'template-posthog-capture',
            name: 'Capture a PostHog event',
            status: 'hidden',
            template_type: 'destination',
            inputs_schema: [
                {
                    key: 'event',
                    type: 'string',
                    label: 'Event name',
                    required: true,
                    description: 'The name of the event to capture.',
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('opening a workflow whose step uses a hidden template renders its config (no "Template not found")', async ({
        page,
    }) => {
        const teamId = workspace!.team_id
        const workflowPayload = buildWorkflowWithCaptureStep()
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
            { teamId, payload: workflowPayload }
        )

        await test.step('open the workflow editor and select the capture step', async () => {
            await page.goto(`/workflows/${workflowId}/workflow`)
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${CAPTURE_NODE_ID}"]`).click()
        })

        await test.step('the template config renders instead of the not-found fallback', async () => {
            // `template-posthog-capture` declares an "Event name" input in its inputs_schema.
            // If the project list omitted hidden templates, the panel would render
            // <div>Template not found!</div> and this label would never appear.
            await expect(page.getByText('Event name', { exact: true })).toBeVisible({ timeout: 15000 })
            await expect(page.getByText('Template not found!')).toHaveCount(0)
        })
    })
})
