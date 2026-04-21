import { randomString } from '../../utils'
import { createEvent, daysAgo } from '../../utils/event-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

const FLAG_KEY = 'e2e-experiment-flag'

function variantProperties(variant: string): Record<string, any> {
    return {
        [`$feature/${FLAG_KEY}`]: variant,
        $feature_flag_response: variant,
        $feature_flag: FLAG_KEY,
    }
}

// 51 users per variant — just above the 50-user minimum for results to render.
// Kept minimal to reduce execution time and flakiness.
const USERS_PER_VARIANT = 51

const experimentEvents = [
    // Exposure events
    ...createEvent({
        event: '$feature_flag_called',
        user: (n) => `control-user-${n}`,
        timestamp: daysAgo(3),
        properties: variantProperties('control'),
    }).repeat(USERS_PER_VARIANT),
    ...createEvent({
        event: '$feature_flag_called',
        user: (n) => `test-user-${n}`,
        timestamp: daysAgo(3),
        properties: variantProperties('test'),
    }).repeat(USERS_PER_VARIANT),

    // Metric events: $pageview — 1 per control user, 1 per test user
    // Kept minimal to reduce execution time and flakiness.
    ...createEvent({
        event: '$pageview',
        user: (n) => `control-user-${n}`,
        timestamp: daysAgo(2),
        properties: variantProperties('control'),
    }).repeat(USERS_PER_VARIANT),
    ...createEvent({
        event: '$pageview',
        user: (n) => `test-user-${n}`,
        timestamp: daysAgo(2),
        properties: variantProperties('test'),
    }).repeat(USERS_PER_VARIANT),
]

test.describe('Experiment lifecycle', () => {
    test.describe('creation and launch', () => {
        let workspace: PlaywrightWorkspaceSetupResult | null = null

        test.beforeEach(async ({ page, playwrightSetup }) => {
            workspace = await playwrightSetup.createWorkspace({
                use_current_time: true,
                skip_onboarding: true,
                no_demo_data: true,
                events: experimentEvents,
            })
            await playwrightSetup.login(page, workspace)
        })

        test('create experiment via wizard, add metrics, and launch', async ({ page }) => {
            const experimentName = randomString('lifecycle-exp')

            await test.step('create experiment via wizard', async () => {
                await page.goto('/experiments/new')
                await expect(page.getByRole('heading', { name: 'New experiment' })).toBeVisible()

                // About step
                await page.getByTestId('experiment-wizard-name').fill(experimentName)
                await page.getByTestId('experiment-wizard-flag-key').fill(FLAG_KEY)
                await page.getByRole('button', { name: 'Continue' }).click()

                // Variants step — wait for stepper to confirm transition
                await expect(page.locator('[aria-current="step"]', { hasText: 'Variant rollout' })).toBeVisible()

                // Customize split to 70/30 — exercises the full variant payload round-trip
                await page.getByRole('button', { name: 'Customize split' }).click()
                const splitInputs = page.getByTestId('experiment-variant-rollout-percentage-input')
                await splitInputs.nth(0).fill('70')
                await splitInputs.nth(1).fill('30')

                await page.getByRole('button', { name: 'Continue' }).click()

                // Analytics step — wait for stepper and step content to render
                await expect(page.locator('[aria-current="step"]', { hasText: 'Analytics' })).toBeVisible()
                await expect(page.getByText('How to measure impact?')).toBeVisible()

                // This click occasionally doesn't produce a navigation. Possible causes:
                // the click not reaching React's event handler after the step transition,
                // or the backend response being slow. Retry until navigation confirms success.
                await expect(async () => {
                    await page.getByRole('button', { name: 'Save as draft' }).click()
                    await page.waitForURL(/\/experiments\/\d+$/, { timeout: 5000 })
                }).toPass({ timeout: 30000 })
                await expect(page.getByTestId('launch-experiment')).toBeVisible()

                // Verify the custom split is preserved
                await page.getByRole('tab', { name: 'Variants' }).click()
                await expect(page.getByText('70%')).toBeVisible()
                await expect(page.getByText('30%')).toBeVisible()
                await page.getByRole('tab', { name: 'Metrics' }).click()
            })

            await test.step('add primary metric', async () => {
                const metricsSection = page.getByTestId('experiment-creation-goal-metric')

                // Pre-condition: no metric exists yet
                await expect(metricsSection.getByText('Pageview')).not.toBeVisible()

                await page.getByRole('button', { name: 'Add primary metric' }).click()

                // Source modal: choose "Single-use"
                await page.getByText('Single-use').click()

                // Metric form opens with $pageview as default — save it and wait for
                // the API response to ensure the metric is persisted before proceeding
                const metricSaveResponse = page.waitForResponse(
                    (resp) =>
                        resp.url().includes('/api/projects/') &&
                        resp.url().includes('/experiments/') &&
                        resp.request().method() === 'PATCH'
                )
                await page.getByTestId('save-experiment-metric').click()
                await metricSaveResponse

                // Post-condition: metric title appears
                await expect(metricsSection.getByText('Pageview')).toBeVisible()
            })

            await test.step('launch experiment', async () => {
                await expect(page.getByTestId('experiment-status')).toContainText('Draft')
                await page.getByTestId('launch-experiment').click()
                await expect(page.getByTestId('experiment-status')).toContainText('Running')
                await expect(page.getByRole('button', { name: 'End experiment' })).toBeVisible()
            })
        })
    })

    // Why a separate test for the running experiment:
    // After launching via the UI, the experiment's start_date is set to "now" by the
    // backend, but pre-seeded events are from days ago. Without backdating start_date
    // (which requires an API call + page reload/navigation), results won't load.
    // Backdating in-page would require a reload, which isn't how a real user navigates.
    // Instead, we use the setup infra to create an already-running experiment with a
    // backdated start_date, so we can test results, pause/resume, and shipping cleanly.
    test.describe('running experiment', () => {
        // Use a wider viewport so the scene panel with pause/resume is visible
        test.use({ viewport: { width: 1920, height: 720 } })

        let workspace: PlaywrightWorkspaceSetupResult | null = null

        test.beforeEach(async ({ page, playwrightSetup }) => {
            workspace = await playwrightSetup.createWorkspace({
                use_current_time: true,
                skip_onboarding: true,
                no_demo_data: true,
                events: experimentEvents,
                experiments: [
                    {
                        name: 'E2E Lifecycle Experiment',
                        feature_flag_key: FLAG_KEY,
                        start_date: daysAgo(5),
                        metrics: [
                            {
                                kind: 'ExperimentMetric',
                                metric_type: 'mean',
                                uuid: 'e2e-primary-metric-1',
                                goal: 'increase',
                                source: {
                                    kind: 'EventsNode',
                                    event: '$pageview',
                                    math: 'total',
                                },
                            },
                        ],
                    },
                ],
            })
            await playwrightSetup.login(page, workspace)
        })

        test('view results, pause, resume, and ship', async ({ page }) => {
            const experimentId = workspace!.created_experiments![0].id

            await test.step('view results', async () => {
                await page.goto(`/experiments/${experimentId}`)
                await expect(page.getByRole('button', { name: 'End experiment' })).toBeVisible()

                const metricsSection = page.getByTestId('experiment-creation-goal-metric')
                await expect(metricsSection.getByText('control').first()).toBeVisible()
                await expect(metricsSection.getByText('test').first()).toBeVisible()
            })

            await test.step('pause experiment', async () => {
                // Pre-condition: experiment is running
                await expect(page.getByTestId('experiment-status')).toContainText('Running')

                // The scene panel is collapsed by default — force it open
                await page.locator('.scene-layout__content-panel').evaluate((el) => el.classList.remove('hidden'))
                await page.getByTestId('pause-experiment').click()

                const modal = page.locator('.LemonModal')
                await expect(modal).toBeVisible()
                await modal.getByRole('button', { name: 'Pause experiment' }).click()

                // Post-condition: status changes to paused
                await expect(page.getByTestId('experiment-status')).toContainText('Paused')
            })

            await test.step('resume experiment', async () => {
                await page.getByTestId('resume-experiment').click()

                const modal = page.locator('.LemonModal')
                await expect(modal).toBeVisible()
                await modal.getByRole('button', { name: 'Resume experiment' }).click()

                // Post-condition: status changes back to running
                await expect(page.getByTestId('experiment-status')).toContainText('Running')
            })

            await test.step('ship winning variant', async () => {
                await page.getByRole('button', { name: 'End experiment' }).click()

                const modal = page.locator('.LemonModal')
                await expect(modal).toBeVisible()

                // Select conclusion
                await modal.getByRole('button', { name: 'Select a value' }).click()
                await page.getByText('Won').first().click()

                // Confirm shipping
                await modal.getByRole('button', { name: 'End experiment' }).click()

                // Verify shipping took effect
                await expect(page.getByTestId('experiment-status')).toContainText('Complete')
                await expect(page.getByText('Won')).toBeVisible()
                await expect(page.getByRole('button', { name: 'End experiment' })).not.toBeVisible()
            })
        })
    })
})
