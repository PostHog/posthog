import { execFileSync } from 'node:child_process'

import { expect, LOGIN_PASSWORD, LOGIN_USERNAME, test } from '../utils/playwright-test-core'

async function callProjectApi(
    page: import('@playwright/test').Page,
    path: string,
    init: { method: string; body?: unknown }
): Promise<any> {
    return await page.evaluate(
        async ({ path, method, body }) => {
            const csrfToken =
                document.cookie
                    .split(';')
                    .map((cookie) => cookie.trim())
                    .find((cookie) => cookie.startsWith('posthog_csrftoken='))
                    ?.split('=')
                    .slice(1)
                    .join('=') || ''

            if (!csrfToken) {
                throw new Error('CSRF cookie missing in browser context')
            }

            const response = await fetch(path, {
                method,
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': decodeURIComponent(csrfToken),
                },
                body: body === undefined ? undefined : JSON.stringify(body),
            })

            if (!response.ok) {
                throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`)
            }

            const text = await response.text()
            return text ? JSON.parse(text) : null
        },
        { path, method: init.method, body: init.body }
    )
}

test.describe('SQL Editor dual-mode synced Postgres source', () => {
    test('live-queries a synced source with direct query enabled', async ({ page }) => {
        test.setTimeout(180000)
        const sourceName = `playwright_dual_${Date.now()}`
        const tableName = `playwright_dual_mode_${Date.now()}`
        let sourceId: string | null = null

        try {
            execFileSync('psql', [
                'postgresql://posthog:posthog@127.0.0.1:5432/posthog',
                '-c',
                `
                    DROP TABLE IF EXISTS ${tableName};
                    CREATE TABLE ${tableName} (
                        id integer primary key,
                        label text not null
                    );
                    INSERT INTO ${tableName} (id, label) VALUES (1, 'alpha'), (2, 'beta');
                `,
            ])
            await page.goto('/login')
            await page.evaluate(
                async ({ email, password }) => {
                    await fetch('/api/login/', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({ email, password }),
                    })
                },
                { email: LOGIN_USERNAME, password: LOGIN_PASSWORD }
            )
            await page.goto('/')
            await expect(page).toHaveURL(/\/project\/\d+/)

            await test.step('Create a synced Postgres source with live queries enabled', async () => {
                const data = await callProjectApi(page, '/api/projects/@current/external_data_sources/', {
                    method: 'POST',
                    body: {
                        source_type: 'Postgres',
                        access_method: 'warehouse',
                        direct_query_enabled: true,
                        prefix: sourceName,
                        payload: {
                            source_type: 'Postgres',
                            host: 'localhost',
                            port: '5432',
                            database: 'posthog',
                            user: 'posthog',
                            password: 'posthog',
                            schema: 'public',
                            schemas: [
                                {
                                    name: tableName,
                                    should_sync: true,
                                    sync_type: null,
                                    incremental_field: null,
                                    incremental_field_type: null,
                                    sync_time_of_day: null,
                                },
                            ],
                        },
                    },
                })
                sourceId = data.id as string
            })

            await test.step('Refresh schemas so schema metadata is captured', async () => {
                await callProjectApi(
                    page,
                    `/api/projects/@current/external_data_sources/${sourceId}/refresh_schemas/`,
                    {
                        method: 'POST',
                    }
                )
            })

            await test.step('Run a HogQL query against the synced connection', async () => {
                await page.goToMenuItem('sql-editor')
                await expect(page.locator('[data-attr=editor-scene]')).toBeVisible({ timeout: 60000 })

                const connectionSelector = page.getByRole('button', { name: /PostHog \(ClickHouse\)/ })
                await connectionSelector.click()
                await page.getByRole('menuitem', { name: `${sourceName} (Postgres · synced)` }).click()

                // CodeEditor lazy-loads monaco, so the container renders before the editor
                // mounts — clicking too early focuses nothing and the keystrokes are lost.
                await page
                    .locator('[data-attr=hogql-query-editor] [data-editor-ready="true"]')
                    .first()
                    .waitFor({ state: 'visible' })
                await page.locator('[data-attr=hogql-query-editor]').click()
                await page
                    .locator('[data-attr=hogql-query-editor]')
                    .press(`${process.platform === 'darwin' ? 'Meta' : 'Control'}+A`)
                await page.locator('[data-attr=hogql-query-editor]').press('Delete')
                // refresh_schemas qualifies schema rows in place (table -> public.table), and the
                // live connection catalog is keyed by the row name — so query the qualified name.
                await page
                    .locator('[data-attr=hogql-query-editor]')
                    .pressSequentially(`SELECT id, label FROM public.${tableName} ORDER BY id`)
                await page.locator('[data-attr=sql-editor-run-button]').click()
                await expect(page.locator('[data-attr=sql-editor-run-button]')).toContainText('Cancel')
                await expect(page.locator('[data-attr=sql-editor-run-button]')).toContainText('Run', { timeout: 60000 })

                await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
                await expect
                    .poll(async () => await page.locator('body').innerText(), { timeout: 60000 })
                    .toContain('alpha')
                await expect
                    .poll(async () => await page.locator('body').innerText(), { timeout: 60000 })
                    .toContain('beta')
            })
        } finally {
            if (sourceId) {
                try {
                    await callProjectApi(page, `/api/projects/@current/external_data_sources/${sourceId}/`, {
                        method: 'DELETE',
                    })
                } catch {
                    // Best-effort cleanup for the source created during the test.
                }
            }
            try {
                execFileSync('psql', [
                    'postgresql://posthog:posthog@127.0.0.1:5432/posthog',
                    '-c',
                    `DROP TABLE IF EXISTS ${tableName};`,
                ])
            } catch {
                // Best-effort cleanup for the table created during the test.
            }
        }
    })
})
