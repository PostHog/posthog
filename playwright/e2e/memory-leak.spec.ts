import { test as base, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import {
    HeapSnapshot,
    MemoryLeakReport,
    analyzeSnapshots,
    createSnapshotDirectory,
    forceGarbageCollection,
    generateReport,
    saveReport,
    takeHeapSnapshot,
    waitForPageStable,
} from '../utils/memory-leak-utils'
import { LOGIN_PASSWORD, LOGIN_USERNAME } from '../utils/playwright-test-core'

const test = base.extend<{ loginBeforeTests: void }>({
    loginBeforeTests: [
        // eslint-disable-next-line react-hooks/rules-of-hooks
        async ({ page }, use) => {
            await page.request.post('/api/login/', {
                data: {
                    email: LOGIN_USERNAME,
                    password: LOGIN_PASSWORD,
                },
            })
            await page.goto(urls.projectHomepage())
            await use()
        },
        { auto: true },
    ],
})

test.describe('Memory Leak Detection', () => {
    test('detects memory leaks across insights and dashboards navigation', async ({ page }) => {
        test.setTimeout(300000)

        const snapshotDir = createSnapshotDirectory()
        // eslint-disable-next-line no-console
        console.log('[memory-leak] Snapshot directory:', snapshotDir)
        const pagesTraversed: string[] = []
        let baselineSnapshot: HeapSnapshot | null = null
        let targetSnapshot: HeapSnapshot | null = null
        let finalSnapshot: HeapSnapshot | null = null

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Taking baseline snapshot at home')
        await waitForPageStable(page)
        await forceGarbageCollection(page)
        baselineSnapshot = await takeHeapSnapshot(page, snapshotDir, 's1-baseline')
        pagesTraversed.push('Home (baseline)')

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Navigating to insights list')
        await page.goto('/insights')
        await waitForPageStable(page)
        pagesTraversed.push('Insights list')

        const insightLinks = await page.locator('a[href*="/insights/"]:not([href*="/new"])').all()
        // eslint-disable-next-line no-console
        console.log(`[memory-leak] Found ${insightLinks.length} insight links`)

        if (insightLinks.length > 1) {
            // eslint-disable-next-line no-console
            console.log('[memory-leak] Opening an insight')
            await insightLinks[1].click()
            await waitForPageStable(page)
            await page.waitForTimeout(2000)
            pagesTraversed.push('Single insight')
        }

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Navigating to dashboards')
        const dashboardsMenu = page.locator('[data-attr="menu-item-dashboards"]')
        if (await dashboardsMenu.isVisible()) {
            await dashboardsMenu.click()
            await waitForPageStable(page)
            pagesTraversed.push('Dashboards list')

            const dashboardLinks = await page.locator('a[href*="/dashboard/"]').all()
            // eslint-disable-next-line no-console
            console.log(`[memory-leak] Found ${dashboardLinks.length} dashboard links`)

            for (const link of dashboardLinks) {
                const href = await link.getAttribute('href')
                if (href && /\/dashboard\/\d+/.test(href)) {
                    // eslint-disable-next-line no-console
                    console.log('[memory-leak] Opening dashboard:', href)
                    await link.click()
                    await waitForPageStable(page)
                    await page.waitForTimeout(4000)
                    pagesTraversed.push(`Dashboard: ${href}`)
                    break
                }
            }
        }

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Scrolling page to trigger potential leaks')
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
        await page.waitForTimeout(1000)
        await page.evaluate(() => window.scrollTo(0, 0))
        await page.waitForTimeout(1000)

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Navigating to SQL editor')
        const sqlEditorMenu = page.locator('[data-attr="menu-item-sql-editor"]')
        if (await sqlEditorMenu.isVisible()) {
            await sqlEditorMenu.click()
            await waitForPageStable(page)
            pagesTraversed.push('SQL Editor')

            const editor = page.locator('[data-attr="hogql-query-editor"]')
            if (await editor.isVisible({ timeout: 5000 }).catch(() => false)) {
                // eslint-disable-next-line no-console
                console.log('[memory-leak] Running SQL queries')
                await editor.click()
                await page.waitForTimeout(500)

                const queries = [
                    'select * from events limit 10',
                    'select * from events limit 100',
                    'select count(*) from events',
                    'select event, count(*) from events group by event limit 20',
                ]

                for (const query of queries) {
                    // eslint-disable-next-line no-console
                    console.log(`[memory-leak] Running query: ${query.substring(0, 30)}...`)

                    await page.keyboard.press('Meta+a')
                    await page.keyboard.type(query, { delay: 20 })

                    const runButton = page.locator('[data-attr="hogql-query-editor-run-button"]')
                    if (await runButton.isVisible().catch(() => false)) {
                        await runButton.click()
                        await page.waitForTimeout(3000)
                    }
                    pagesTraversed.push(`SQL Query: ${query.substring(0, 20)}...`)
                }

                // eslint-disable-next-line no-console
                console.log('[memory-leak] Scrolling SQL results')
                await page.evaluate(() => {
                    const resultsPane = document.querySelector('.DataTable, [class*="results"]')
                    if (resultsPane) {
                        resultsPane.scrollTop = resultsPane.scrollHeight
                        resultsPane.scrollTop = 0
                    }
                })
                await page.waitForTimeout(1000)
            }
        }

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Navigating to Session Replay')
        const sessionReplayMenu = page.locator('[data-attr="menu-item-replay"]')
        if (await sessionReplayMenu.isVisible()) {
            await sessionReplayMenu.click()
            await waitForPageStable(page)
            pagesTraversed.push('Session Replay')

            await page.keyboard.press('Escape')
            await page.waitForTimeout(1000)

            const recordings = page.locator('[data-attr="select-recording"]')
            const recordingCount = await recordings.count()
            // eslint-disable-next-line no-console
            console.log(`[memory-leak] Found ${recordingCount} recordings`)

            if (recordingCount > 0) {
                // eslint-disable-next-line no-console
                console.log('[memory-leak] Opening first recording')
                await recordings.first().click()
                await page.waitForTimeout(3000)
                pagesTraversed.push('Recording 1')

                // eslint-disable-next-line no-console
                console.log('[memory-leak] Switching between recordings')
                for (let i = 1; i < Math.min(3, recordingCount); i++) {
                    const freshRecordings = page.locator('[data-attr="select-recording"]')
                    const recording = freshRecordings.nth(i)
                    if (await recording.isVisible().catch(() => false)) {
                        await recording.click()
                        await page.waitForTimeout(2000)
                        pagesTraversed.push(`Recording ${i + 1}`)
                    }
                }
            }
        }

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Taking target snapshot')
        await forceGarbageCollection(page)
        targetSnapshot = await takeHeapSnapshot(page, snapshotDir, 's2-target')

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Navigating back to home')
        const homeLink = page.locator('[data-attr="menu-item-projecthomepage"]')
        if (await homeLink.isVisible()) {
            await homeLink.click()
        } else {
            await page.goto(urls.projectHomepage())
        }
        await waitForPageStable(page)
        await page.waitForTimeout(2000)
        pagesTraversed.push('Home (final)')

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Taking final snapshot')
        await forceGarbageCollection(page)
        finalSnapshot = await takeHeapSnapshot(page, snapshotDir, 's3-final')

        // eslint-disable-next-line no-console
        console.log('[memory-leak] Analyzing snapshots')
        const leakResults = await analyzeSnapshots(baselineSnapshot, targetSnapshot, finalSnapshot)

        const report: MemoryLeakReport = {
            pagesTraversed,
            snapshots: {
                baseline: baselineSnapshot,
                target: targetSnapshot,
                final: finalSnapshot,
            },
            leakResults,
            timestamp: new Date().toISOString(),
        }

        const reportPath = saveReport(report, snapshotDir)
        // eslint-disable-next-line no-console
        console.log('[memory-leak] Report saved to:', reportPath)

        const markdownReport = generateReport(report)
        // eslint-disable-next-line no-console
        console.log('\n' + markdownReport)

        expect(baselineSnapshot).toBeTruthy()
        expect(targetSnapshot).toBeTruthy()
        expect(finalSnapshot).toBeTruthy()
    })
})
