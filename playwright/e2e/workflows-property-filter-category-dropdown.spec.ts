import { expect } from '@playwright/test'

import { mockFeatureFlags } from '../utils/mockApi'
import { test } from '../utils/playwright-test-base'

const TRIGGER_NODE_ID = 'trigger_node'
const EXIT_NODE_ID = 'exit_node'
const CONDITIONAL_BRANCH_ID = 'conditional_branch_node'

function buildConditionalBranchWorkflow(): Record<string, any> {
    return {
        name: `Property filter category dropdown bug ${Date.now()}`,
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
                id: CONDITIONAL_BRANCH_ID,
                type: 'conditional_branch',
                name: 'Conditional branch',
                description: 'Branch on event property',
                created_at: 0,
                updated_at: 0,
                config: {
                    conditions: [
                        {
                            filters: {
                                properties: [
                                    {
                                        key: '$browser',
                                        type: 'event',
                                        value: 'Chrome',
                                        operator: 'exact',
                                    },
                                ],
                            },
                        },
                    ],
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
            { from: TRIGGER_NODE_ID, to: CONDITIONAL_BRANCH_ID, type: 'continue' },
            { from: CONDITIONAL_BRANCH_ID, to: EXIT_NODE_ID, type: 'branch', index: 0 },
            { from: CONDITIONAL_BRANCH_ID, to: EXIT_NODE_ID, type: 'continue' },
        ],
        conversion: { window_minutes: null, filters: [] },
        exit_condition: 'exit_only_at_end',
        version: 1,
        status: 'draft',
    }
}

test.describe('Workflows conditional branch property filter category dropdown', () => {
    test.beforeEach(async ({ page }) => {
        await mockFeatureFlags(page, {
            'taxonomic-filter-category-dropdown': 'pill',
        })
    })

    test('reopening a saved filter and clicking the category dropdown trigger pill keeps the filter popover open', async ({
        page,
    }) => {
        test.setTimeout(90 * 1000)
        const me = await page.request.get('/api/users/@me/')
        expect(me.ok()).toBe(true)
        const meData = await me.json()
        const teamId: number = meData.team.id

        const workflowPayload = buildConditionalBranchWorkflow()
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

        await test.step('open the workflow editor and select the conditional branch', async () => {
            await page.goto(`/workflows/${workflowId}/workflow`)
            await page.waitForSelector('[data-attr="workflow-editor"]', { timeout: 30000 })
            await page.locator(`[data-testid="rf__node-${CONDITIONAL_BRANCH_ID}"]`).click()
            await expect(page.getByTestId('property-filter-0')).toBeVisible()
        })

        await test.step('reopen the saved filter popover', async () => {
            await page.getByTestId('property-filter-0').locator('.PropertyFilterButton').click()
            await expect(page.getByTestId('property-select-toggle-0')).toBeVisible()
        })

        await test.step('open the inner taxonomic filter dropdown', async () => {
            await page.getByTestId('property-select-toggle-0').click()
            await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeVisible()
            await expect(page.getByTestId('taxonomic-category-dropdown-trigger-pill')).toBeVisible()
        })

        await test.step('clicking the category dropdown trigger pill opens the menu and keeps the popover open', async () => {
            await page.getByTestId('taxonomic-category-dropdown-trigger-pill').click()
            // Give the popover transitions time to settle so the assertions reflect the steady state
            // after the click rather than the brief moment between mouseup and click-outside.
            await page.waitForTimeout(250)
            await expect(page.getByTestId('property-filter-0')).toBeVisible()
            await expect(page.getByTestId('property-select-toggle-0')).toBeVisible()
            await expect(page.getByTestId('taxonomic-filter-searchfield')).toBeVisible()
            await expect(page.getByTestId('taxonomic-category-dropdown-item-event_properties')).toBeVisible()
        })
    })
})
