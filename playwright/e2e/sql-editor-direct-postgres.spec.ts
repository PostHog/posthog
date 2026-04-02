import { execFileSync } from 'node:child_process'

import { mockFeatureFlags } from '../utils/mockApi'
import { expect, LOGIN_PASSWORD, LOGIN_USERNAME, test } from '../utils/playwright-test-core'

test.describe('SQL Editor direct Postgres queries', () => {
    test('creates a Postgres direct source and queries it successfully', async ({ page }) => {
        test.setTimeout(180000)
        const sourceName = `Playwright direct ${Date.now()}`
        const tableName = `playwright_direct_query_${Date.now()}`
        let sourceId: string | null = null

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

        try {
            await mockFeatureFlags(page, {
                'dwh-postgres-direct-query': true,
            })

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
            await page.goToMenuItem('sql-editor')
            await expect(page.locator('[data-attr=editor-scene]')).toBeVisible({ timeout: 60000 })

            await test.step('Open the direct Postgres source flow with direct query preselected', async () => {
                await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).toBeVisible()

                const connectionSelector = page.getByRole('button', { name: /PostHog \(ClickHouse\)/ })
                await connectionSelector.click()
                await page.getByRole('menuitem', { name: '+ Add postgres direct connection' }).click()

                await expect(page).toHaveURL(/.*\/data-warehouse\/new-source/)
                await expect(page).toHaveURL(/kind=Postgres/)
                await expect(page).toHaveURL(/access_method=direct/)
                await expect(page.getByText('How should PostHog query this source?')).toBeVisible({ timeout: 60000 })
                await expect(page.getByText('Shown as:')).toBeVisible({ timeout: 60000 })
            })

            await test.step('Create the Postgres direct source for the selected table', async () => {
                sourceId = await page.evaluate(
                    async ({ name, table }) => {
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

                        const response = await fetch('/api/projects/@current/external_data_sources/', {
                            method: 'POST',
                            credentials: 'include',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-CSRFToken': decodeURIComponent(csrfToken),
                            },
                            body: JSON.stringify({
                                source_type: 'Postgres',
                                access_method: 'direct',
                                prefix: name,
                                payload: {
                                    source_type: 'Postgres',
                                    host: '127.0.0.1',
                                    port: '5432',
                                    database: 'posthog',
                                    user: 'posthog',
                                    password: 'posthog',
                                    schema: 'public',
                                    schemas: [
                                        {
                                            name: table,
                                            should_sync: true,
                                            sync_type: null,
                                            incremental_field: null,
                                            incremental_field_type: null,
                                            sync_time_of_day: null,
                                        },
                                    ],
                                },
                            }),
                        })

                        if (!response.ok) {
                            throw new Error(`${response.status} ${await response.text()}`)
                        }

                        const data = await response.json()
                        return data.id as string
                    },
                    { name: sourceName, table: tableName }
                )
            })

            await test.step('Run a successful raw query against the new connection', async () => {
                await page.goto('/')
                await page.goToMenuItem('sql-editor')
                await expect(page.locator('[data-attr=editor-scene]')).toBeVisible({ timeout: 60000 })

                const connectionSelector = page.getByRole('button', { name: /PostHog \(ClickHouse\)/ })
                await connectionSelector.click()
                await page.getByRole('menuitem', { name: `${sourceName} (Postgres)` }).click()

                await page.getByTestId('sql-editor-settings-toggle').click()
                await page.getByTestId('sql-editor-send-raw-query-toggle').click()

                await page.locator('[data-attr=hogql-query-editor]').click()
                await page
                    .locator('[data-attr=hogql-query-editor]')
                    .press(`${process.platform === 'darwin' ? 'Meta' : 'Control'}+A`)
                await page.locator('[data-attr=hogql-query-editor]').press('Delete')
                await page
                    .locator('[data-attr=hogql-query-editor]')
                    .pressSequentially(`SELECT id, label FROM ${tableName} ORDER BY id`)
                await page.locator('[data-attr=sql-editor-run-button]').click()

                await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
                await expect
                    .poll(async () => await page.locator('body').innerText(), { timeout: 15000 })
                    .toContain('Showing 2 rows')
                await expect
                    .poll(async () => await page.locator('body').innerText(), { timeout: 15000 })
                    .toContain('alpha')
            })
        } finally {
            if (sourceId) {
                try {
                    await page.evaluate(
                        async ({ id }) => {
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

                            await fetch(`/api/projects/@current/external_data_sources/${id}/`, {
                                method: 'DELETE',
                                credentials: 'include',
                                headers: {
                                    'X-CSRFToken': decodeURIComponent(csrfToken),
                                },
                            })
                        },
                        { id: sourceId }
                    )
                } catch {
                    // Best-effort cleanup for the source created during the test.
                }
            }
            execFileSync('psql', [
                'postgresql://posthog:posthog@127.0.0.1:5432/posthog',
                '-c',
                `DROP TABLE IF EXISTS ${tableName};`,
            ])
        }
    })
})
