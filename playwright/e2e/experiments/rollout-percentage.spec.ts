import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Experiment Rollout Percentage', () => {
    test('shows rollout percentage as well as complex release conditions', async ({ page }) => {
        const flagKey = randomString('rollout-test-flag')
        let featureFlagTeamId: number
        let featureFlagId: number
        let featureFlagFilters: Record<string, any>

        // Step 1: Create experiment via the UI with 80% rollout
        await page.goto('/experiments/new')

        await test.step('fill out experiment creation form', async () => {
            // Set experiment name
            await page.getByPlaceholder('Enter name').fill('Rollout Percentage E2E Test')

            // Select feature flag
            const flagKeyValidationPromise = page.waitForResponse(
                (resp) => resp.url().includes('/feature_flags/') && resp.request().method() === 'GET' && resp.ok()
            )
            await page.getByPlaceholder('Type to create a new feature flag or select an existing one').fill(flagKey)
            await page.getByText(`${flagKey} (new feature flag)`).click()
            await flagKeyValidationPromise

            // Set rollout percentage to 80%
            const rolloutInput = page.locator('[data-attr="experiment-rollout-percentage-input"]')
            await rolloutInput.scrollIntoViewIfNeeded()
            await rolloutInput.clear()
            await rolloutInput.fill('80')

            // Leave metrics empty so that when saving we stay in draft mode
            const savePromise = page.waitForResponse(
                (resp) => resp.url().includes('/experiments/') && resp.request().method() === 'POST' && resp.ok()
            )
            await page.locator('[data-attr="save-experiment"]').first().click()
            const saveResponse = await savePromise
            const experimentData = await saveResponse.json()
            featureFlagTeamId = experimentData.feature_flag.team_id
            featureFlagId = experimentData.feature_flag.id
            featureFlagFilters = experimentData.feature_flag.filters
        })

        // Step 2: Verify 80% rollout in the linked feature flag section
        await test.step('verify 80% rollout on experiment page', async () => {
            await expect(page.getByText('80% of all users')).toBeVisible()
        })

        // Step 3: Add a second condition set via the feature flag API
        await test.step('add a second condition set via API', async () => {
            const updatedGroups = [
                ...featureFlagFilters.groups,
                {
                    properties: [
                        {
                            key: 'email',
                            value: ['example@test.com'],
                            operator: 'exact',
                            type: 'person',
                        },
                    ],
                    rollout_percentage: 50,
                },
            ]

            const patchResult = await page.evaluate(
                async ({ url, filters }) => {
                    const cookie = document.cookie.split('; ').find((c) => c.startsWith('posthog_csrftoken='))
                    const csrfToken = cookie ? cookie.split('=')[1] : ''
                    const res = await fetch(url, {
                        method: 'PATCH',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken,
                        },
                        body: JSON.stringify({ filters }),
                    })
                    return { ok: res.ok, status: res.status, body: await res.text() }
                },
                {
                    url: `/api/projects/${featureFlagTeamId}/feature_flags/${featureFlagId}/`,
                    filters: { ...featureFlagFilters, groups: updatedGroups },
                }
            )
            if (!patchResult.ok) {
                console.error('Feature flag PATCH failed:', patchResult.status, patchResult.body)
            }
            expect(patchResult.ok).toBe(true)

            await page.reload()
        })

        // Step 4: Verify both conditions are shown in the linked feature flag section
        await test.step('verify both condition sets on experiment page', async () => {
            await expect(page.getByText('Linked feature flag')).toBeVisible()
            await expect(page.getByText('80% of all users')).toBeVisible()
            await expect(page.getByText('50% of users matching 1 condition')).toBeVisible()
        })
    })
})
