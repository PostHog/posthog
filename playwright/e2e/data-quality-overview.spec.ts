/**
 * Editing and deleting a data quality check from the Data Ops overview.
 */
import { expect } from '@playwright/test'

import { FEATURE_FLAGS } from '../../frontend/src/lib/constants'
import { mockFeatureFlags } from '../utils/mockApi'
import { test } from '../utils/workspace-test-base'

const CHECK_NAME = 'orders_has_rows'
const SUBJECT_NAME = 'orders_e2e'

test('edits and deletes a check from Data Ops', async ({ page, playwrightSetup }) => {
    const workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true })
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
    await page.getByRole('menuitem', { name: 'Edit' }).click()
    await page.getByLabel('Description').fill('Every order keeps a positive id')
    await page.getByTestId('data-quality-check-save').click()

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
