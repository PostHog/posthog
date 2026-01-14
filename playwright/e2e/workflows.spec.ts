/**
 * Screenshot tests for workflows product
 */
import { expect } from '@playwright/test'

import { test } from '../utils/workspace-test-base'

test.describe('Workflows', () => {
    test('workflows list page', async ({ page, playwrightSetup }) => {
        // Create workspace with API key
        const workspace = await playwrightSetup.createWorkspace('Workflows Test Org')

        // Create a few test workflows via API
        const workflow1 = await page.request.post(`/api/projects/${workspace.team_id}/hog_flows/`, {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                name: 'Test Workflow 1',
                description: 'A test workflow for screenshot testing',
                status: 'active',
                exit_condition: 'exit_only_at_end',
                actions: [
                    {
                        id: 'trigger_1',
                        name: 'Trigger',
                        description: 'Manual trigger',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'manual',
                        },
                    },
                    {
                        id: 'action_1',
                        name: 'Test Action',
                        description: 'A test action',
                        type: 'wait',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            minutes: 5,
                        },
                    },
                ],
                edges: [
                    {
                        from: 'trigger_1',
                        to: 'action_1',
                        type: 'continue',
                    },
                ],
            },
        })

        expect(workflow1.ok()).toBe(true)

        const workflow2 = await page.request.post(`/api/projects/${workspace.team_id}/hog_flows/`, {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                name: 'Test Workflow 2',
                description: 'Another test workflow',
                status: 'draft',
                exit_condition: 'exit_only_at_end',
                actions: [
                    {
                        id: 'trigger_2',
                        name: 'Scheduled Trigger',
                        description: 'Runs daily',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'schedule',
                            scheduled_at: '2024-12-01T00:00:00Z',
                        },
                    },
                ],
                edges: [],
            },
        })

        expect(workflow2.ok()).toBe(true)

        // Navigate to workflows list page
        await page.goto(`/project/${workspace.team_id}/workflows`)

        // Wait for the page to load
        await page.waitForSelector('[data-attr="new-workflow"]', { timeout: 10000 })

        // Take a screenshot of the workflows list page
        await expect(page).toHaveScreenshot('workflows-list.png', {
            fullPage: true,
            maxDiffPixelRatio: 0.01,
        })
    })

    test('workflow detail page', async ({ page, playwrightSetup }) => {
        // Create workspace with API key
        const workspace = await playwrightSetup.createWorkspace('Workflows Detail Test Org')

        // Create a test workflow via API
        const workflowResponse = await page.request.post(`/api/projects/${workspace.team_id}/hog_flows/`, {
            headers: {
                Authorization: `Bearer ${workspace.personal_api_key}`,
                'Content-Type': 'application/json',
            },
            data: {
                name: 'Test Workflow Detail',
                description: 'A workflow for testing the detail page',
                status: 'active',
                exit_condition: 'exit_only_at_end',
                actions: [
                    {
                        id: 'trigger_1',
                        name: 'Manual Trigger',
                        description: 'Start the workflow manually',
                        type: 'trigger',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            type: 'manual',
                        },
                    },
                    {
                        id: 'action_1',
                        name: 'Wait Step',
                        description: 'Wait for 10 minutes',
                        type: 'wait',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            minutes: 10,
                        },
                    },
                    {
                        id: 'action_2',
                        name: 'Exit',
                        description: 'End the workflow',
                        type: 'exit',
                        created_at: Date.now(),
                        updated_at: Date.now(),
                        config: {
                            reason: 'Completed successfully',
                        },
                    },
                ],
                edges: [
                    {
                        from: 'trigger_1',
                        to: 'action_1',
                        type: 'continue',
                    },
                    {
                        from: 'action_1',
                        to: 'action_2',
                        type: 'continue',
                    },
                ],
            },
        })

        expect(workflowResponse.ok()).toBe(true)
        const workflowData = await workflowResponse.json()
        expect(workflowData.id).toBeTruthy()

        // Navigate to workflow detail page
        await page.goto(`/project/${workspace.team_id}/workflows/${workflowData.id}/workflow`)

        // Wait for the workflow detail page to load
        await page.waitForSelector('.workflow-canvas, .ReactFlow', { timeout: 10000 })

        // Take a screenshot of the workflow detail page
        await expect(page).toHaveScreenshot('workflow-detail.png', {
            fullPage: true,
            maxDiffPixelRatio: 0.01,
        })
    })
})
