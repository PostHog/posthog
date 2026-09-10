/**
 * Editing and deleting a data quality check from the Data Ops overview.
 */
import { expect } from '@playwright/test'

import { FEATURE_FLAGS } from '../../frontend/src/lib/constants'
import { mockFeatureFlags } from '../utils/mockApi'
import { test } from '../utils/workspace-test-base'

const CHECK_NAME = 'orders_has_rows'
const SUBJECT_NAME = 'orders_e2e'

test('authors and runs a custom SQL check against a saved metric', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    const auth = { headers: { Authorization: `Bearer ${workspace.personal_api_key}` } }
    const metricName = 'orders_metric_e2e'
    const checkName = 'orders_metric_positive'
    const metricResponse = await page.request.post(`/api/projects/${workspace.team_id}/data_catalog/metrics/`, {
        ...auth,
        data: {
            name: metricName,
            description: 'An invented order count for browser verification',
            definition: { kind: 'HogQLQuery', query: 'SELECT 1 AS orders' },
        },
    })
    expect(metricResponse.ok()).toBe(true)
    const metricId = (await metricResponse.json()).id
    const unsupportedResponse = await page.request.post(`/api/projects/${workspace.team_id}/data_catalog/metrics/`, {
        ...auth,
        data: { name: 'orders_manual_e2e', description: 'A metric awaiting a query definition' },
    })
    expect(unsupportedResponse.ok()).toBe(true)

    await mockFeatureFlags(page, {
        [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
        [FEATURE_FLAGS.DATA_QUALITY_CHECKS]: true,
    })
    await page.addInitScript(() => {
        ;(window as any).__PERF_MONACO_HOOK__ = true
    })
    const userResponse = await page.request.patch('/api/users/@me/', {
        ...auth,
        data: { has_seen_product_intro_for: { posthog_ai_onboarding: true } },
    })
    expect(userResponse.ok()).toBe(true)
    await playwrightSetup.loginAndNavigateToTeam(page, workspace)
    await page.goto(`/data-catalog/metrics/${metricName}?tab=tests`)
    await expect(page.getByText('No checks yet', { exact: true })).toBeVisible()
    await expect(page.getByTestId('data-quality-schedule-enabled')).toHaveCount(0)

    await page.getByTestId('data-quality-first-check').click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByText('FROM {metric}', { exact: false })).toBeVisible()
    await expect
        .poll(() => page.evaluate(() => (window as any).__monacoEditors?.at(-1)?.getModel()?.getValue()))
        .toBe('SELECT *\nFROM {metric}\nWHERE <failure condition>')
    await page.evaluate(() => {
        const editor = (window as any).__monacoEditors.at(-1)
        editor.focus()
        editor.setSelection(editor.getModel().getFullModelRange())
        editor.trigger('keyboard', 'paste', { text: 'SELECT * FROM {metric} WHERE orders > 0' })
    })
    await page.getByPlaceholder('orders_customer_id_not_null').fill(checkName)
    await page.getByTestId('data-quality-check-save').click()
    await expect(page.getByRole('dialog')).toHaveCount(0)
    await expect(page.getByText(checkName, { exact: true })).toBeVisible()
    await expect(page.getByTestId('data-quality-schedule-interval')).toHaveText('Daily')

    const scheduleUrl = `/api/projects/${workspace.team_id}/data_catalog/metrics/${metricId}/checks/schedule/`
    const pauseResponse = page.waitForResponse(
        (response) => response.url().endsWith(scheduleUrl) && response.request().method() === 'PATCH'
    )
    await page.getByTestId('data-quality-schedule-enabled').click()
    expect((await (await pauseResponse).json()).next_run_at).toBeNull()
    await expect(page.getByText('Next run', { exact: false })).toHaveCount(0)
    await page.getByTestId('data-quality-schedule-interval').click()
    await page.getByRole('menuitem', { name: 'Every 6 hours', exact: true }).click()
    await expect(page.getByTestId('data-quality-schedule-interval')).toHaveText('Every 6 hours')
    await page.reload()
    await expect(page.getByTestId('data-quality-schedule-interval')).toHaveText('Every 6 hours')
    await expect(page.getByTestId('data-quality-schedule-enabled')).toHaveAttribute('aria-checked', 'false')

    await page.route(`**${scheduleUrl}`, async (route) => {
        if (route.request().method() === 'PATCH') {
            await route.fulfill({ status: 503, json: { detail: 'Schedule service unavailable' } })
        } else {
            await route.continue()
        }
    })
    await page.getByTestId('data-quality-schedule-enabled').click()
    await expect(page.getByText('Could not confirm the schedule update. Reload it before trying again.')).toBeVisible()
    await expect(page.getByTestId('data-quality-schedule-enabled')).toBeDisabled()
    await page.unroute(`**${scheduleUrl}`)
    await page.getByRole('button', { name: 'Reload', exact: true }).click()
    await expect(page.getByTestId('data-quality-schedule-enabled')).toBeEnabled()
    await expect(page.getByTestId('data-quality-schedule-enabled')).toHaveAttribute('aria-checked', 'false')

    await page.getByLabel(`Actions for check ${checkName}`).click()
    await page.getByRole('menuitem', { name: 'Run now', exact: true }).click()
    await expect(page.getByText('failed', { exact: true })).toBeVisible({ timeout: 60000 })
    await page.getByText('Run history', { exact: true }).click()
    await expect(page.getByText('0 passed, 1 failed, 0 errored, 0 skipped')).toBeVisible()
    await expect(page.getByText('manual', { exact: true })).toBeVisible()

    await page.goto('/data-ops?tab=data-quality')
    const metricPagePromise = page.waitForEvent('popup')
    await page.getByRole('link', { name: metricName, exact: true }).click()
    const metricPage = await metricPagePromise
    await expect(metricPage).toHaveURL(new RegExp(`/data-catalog/metrics/${metricName}\\?tab=tests`))
    await mockFeatureFlags(metricPage, {
        [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
        [FEATURE_FLAGS.DATA_QUALITY_CHECKS]: true,
    })
    await metricPage.reload()
    await expect(metricPage.getByText(checkName, { exact: true })).toBeVisible()
    await metricPage.close()

    await page.goto('/data-catalog/metrics/orders_manual_e2e?tab=tests')
    await expect(page.getByText(/Tests are available for SQL metrics only/)).toBeVisible()
    await expect(page.getByTestId('data-quality-new-check')).toHaveCount(0)
    await expect(page.getByTestId('data-quality-first-check')).toHaveCount(0)
})

test('edits and deletes a check from Data Ops', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    const auth = {
        headers: {
            Authorization: `Bearer ${workspace.personal_api_key}`,
            'Content-Type': 'application/json',
        },
    }

    const savedQuery = await page.request.post(`/api/projects/${workspace.team_id}/warehouse_saved_queries/`, {
        ...auth,
        data: { name: SUBJECT_NAME, query: { kind: 'HogQLQuery', query: 'SELECT 1 AS id' } },
    })
    expect(savedQuery.ok()).toBe(true)
    const savedQueryId = (await savedQuery.json()).id

    const created = await page.request.post(
        `/api/projects/${workspace.team_id}/warehouse_saved_queries/${savedQueryId}/checks/`,
        {
            ...auth,
            data: {
                name: CHECK_NAME,
                check_type: 'custom_sql',
                column_name: '',
                config: { query: 'SELECT id FROM orders_e2e WHERE id < 0' },
            },
        }
    )
    expect(created.ok()).toBe(true)
    const check = await created.json()

    await mockFeatureFlags(page, {
        [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
        [FEATURE_FLAGS.DATA_QUALITY_CHECKS]: true,
    })
    await playwrightSetup.loginAndNavigateToTeam(page, workspace)
    await page.goto('/data-ops?tab=data-quality')

    await page.getByLabel(`Expand checks for ${SUBJECT_NAME}`).click({ timeout: 30000 })
    await expect(page.getByText(CHECK_NAME)).toBeVisible()

    await page.getByLabel(`Actions for check ${CHECK_NAME}`).click()
    const metadataResponse = page.waitForResponse(
        (response) =>
            response.url().includes('/query/HogQLMetadata/') && response.request().method() === 'POST' && response.ok()
    )
    await page.getByRole('menuitem', { name: 'Edit' }).click()
    await metadataResponse
    await page.getByLabel('Description').fill('Every order keeps a positive id')
    const saveButton = page.getByTestId('data-quality-check-save')
    await expect(saveButton).toBeEnabled()
    await saveButton.click()

    await expect(page.getByText('Check saved')).toBeVisible()
    const edited = await page.request.get(
        `/api/projects/${workspace.team_id}/warehouse_saved_queries/${savedQueryId}/checks/${check.id}/`,
        auth
    )
    const editedCheck = await edited.json()
    // The point of the whole change: an edit refines the check rather than replacing it.
    expect(editedCheck.id).toEqual(check.id)
    expect(editedCheck.description).toEqual('Every order keeps a positive id')
    expect(editedCheck.last_status).toEqual(check.last_status)
    expect(editedCheck.last_run_at).toEqual(check.last_run_at)

    await page.getByLabel(`Actions for check ${CHECK_NAME}`).click()
    await page.getByRole('menuitem', { name: 'Delete' }).click()
    await page.getByRole('button', { name: 'Delete' }).click()

    await expect(page.getByText(CHECK_NAME)).toHaveCount(0)
})
