import { Page, test as base, expect } from '@playwright/test'

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

const log = (message: string): void => {
    // eslint-disable-next-line no-console
    console.log(`[memory-leak] ${message}`)
}

const test = base.extend<{ loginBeforeTests: void }>({
    loginBeforeTests: [
        // eslint-disable-next-line react-hooks/rules-of-hooks
        async ({ page }, use) => {
            await page.request.post('/api/login/', {
                data: { email: LOGIN_USERNAME, password: LOGIN_PASSWORD },
            })
            await page.goto(urls.projectHomepage())
            await use()
        },
        { auto: true },
    ],
})

interface MemoryLeakTestContext {
    page: Page
    testName: string
    snapshotDir: string
    pagesTraversed: string[]
}

async function takeThreeSnapshots(
    ctx: MemoryLeakTestContext,
    targetActions: () => Promise<void>
): Promise<{ baseline: HeapSnapshot; target: HeapSnapshot; final: HeapSnapshot }> {
    log('Taking baseline snapshot')
    await waitForPageStable(ctx.page)
    await forceGarbageCollection(ctx.page)
    const baseline = await takeHeapSnapshot(ctx.page, ctx.snapshotDir, 's1-baseline')
    ctx.pagesTraversed.push('Baseline')

    await targetActions()

    log('Taking target snapshot')
    await forceGarbageCollection(ctx.page)
    const target = await takeHeapSnapshot(ctx.page, ctx.snapshotDir, 's2-target')

    log('Navigating back to home')
    const homeLink = ctx.page.locator('[data-attr="menu-item-projecthomepage"]')
    if (await homeLink.isVisible()) {
        await homeLink.click()
    } else {
        await ctx.page.goto(urls.projectHomepage())
    }
    await waitForPageStable(ctx.page)
    await ctx.page.waitForTimeout(2000)
    ctx.pagesTraversed.push('Home (final)')

    log('Taking final snapshot')
    await forceGarbageCollection(ctx.page)
    const final = await takeHeapSnapshot(ctx.page, ctx.snapshotDir, 's3-final')

    return { baseline, target, final }
}

function generateAndSaveReport(
    ctx: MemoryLeakTestContext,
    snapshots: { baseline: HeapSnapshot; target: HeapSnapshot; final: HeapSnapshot },
    leakResults: Awaited<ReturnType<typeof analyzeSnapshots>>
): void {
    const report: MemoryLeakReport = {
        testName: ctx.testName,
        pagesTraversed: ctx.pagesTraversed,
        snapshots,
        leakResults,
        timestamp: new Date().toISOString(),
    }

    const reportPath = saveReport(report, ctx.snapshotDir)
    log(`Report saved to: ${reportPath}`)

    const markdownReport = generateReport(report)
    // eslint-disable-next-line no-console
    console.log('\n' + markdownReport)
}

test.describe('Memory Leak Detection', () => {
    test('detects memory leaks when navigating between homepage and settings', async ({ page }) => {
        test.setTimeout(300000)

        const ctx: MemoryLeakTestContext = {
            page,
            testName: 'Homepage ↔ Settings Navigation',
            snapshotDir: createSnapshotDirectory('homepage-settings'),
            pagesTraversed: [],
        }
        log(`Snapshot directory: ${ctx.snapshotDir}`)

        const snapshots = await takeThreeSnapshots(ctx, async () => {
            const iterations = 5
            log(`Navigating between homepage and settings ${iterations} times`)

            for (let i = 0; i < iterations; i++) {
                log(`Iteration ${i + 1}/${iterations}: Navigating to settings`)
                const settingsMenu = page.locator('[data-attr="menu-item-settings"]')
                if (await settingsMenu.isVisible()) {
                    await settingsMenu.click()
                } else {
                    await page.goto('/settings/project')
                }
                await waitForPageStable(page)
                await page.waitForTimeout(1000)
                ctx.pagesTraversed.push(`Settings (iteration ${i + 1})`)

                log(`Iteration ${i + 1}/${iterations}: Navigating back to homepage`)
                const homeMenu = page.locator('[data-attr="menu-item-projecthomepage"]')
                if (await homeMenu.isVisible()) {
                    await homeMenu.click()
                } else {
                    await page.goto(urls.projectHomepage())
                }
                await waitForPageStable(page)
                await page.waitForTimeout(1000)
                ctx.pagesTraversed.push(`Homepage (iteration ${i + 1})`)
            }
        })

        const leakResults = await analyzeSnapshots(snapshots.baseline, snapshots.target, snapshots.final)
        generateAndSaveReport(ctx, snapshots, leakResults)

        expect(snapshots.baseline).toBeTruthy()
        expect(snapshots.target).toBeTruthy()
        expect(snapshots.final).toBeTruthy()
    })

    test('detects memory leaks across insights and dashboards navigation', async ({ page }) => {
        test.setTimeout(300000)

        const ctx: MemoryLeakTestContext = {
            page,
            testName: 'Insights & Dashboards Navigation',
            snapshotDir: createSnapshotDirectory('navigation'),
            pagesTraversed: [],
        }
        log(`Snapshot directory: ${ctx.snapshotDir}`)

        const snapshots = await takeThreeSnapshots(ctx, async () => {
            log('Navigating to insights list')
            await page.goto('/insights')
            await waitForPageStable(page)
            ctx.pagesTraversed.push('Insights list')

            const insightLinks = await page.locator('a[href*="/insights/"]:not([href*="/new"])').all()
            log(`Found ${insightLinks.length} insight links`)

            if (insightLinks.length > 1) {
                log('Opening an insight')
                await insightLinks[1].click()
                await waitForPageStable(page)
                await page.waitForTimeout(2000)
                ctx.pagesTraversed.push('Single insight')
            }

            log('Navigating to dashboards')
            const dashboardsMenu = page.locator('[data-attr="menu-item-dashboards"]')
            if (await dashboardsMenu.isVisible()) {
                await dashboardsMenu.click()
                await waitForPageStable(page)
                ctx.pagesTraversed.push('Dashboards list')

                await openFirstDashboard(page, ctx)
            }

            log('Scrolling page')
            await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
            await page.waitForTimeout(1000)
            await page.evaluate(() => window.scrollTo(0, 0))
            await page.waitForTimeout(1000)

            await navigateToSqlEditor(page, ctx)
            await navigateToSessionReplay(page, ctx)
        })

        const leakResults = await analyzeSnapshots(snapshots.baseline, snapshots.target, snapshots.final)
        generateAndSaveReport(ctx, snapshots, leakResults)

        expect(snapshots.baseline).toBeTruthy()
        expect(snapshots.target).toBeTruthy()
        expect(snapshots.final).toBeTruthy()
    })

    test('detects memory leaks when toggling dashboard filters', async ({ page }) => {
        test.setTimeout(300000)

        const ctx: MemoryLeakTestContext = {
            page,
            testName: 'Dashboard Filter Toggling',
            snapshotDir: createSnapshotDirectory('dashboard-filters'),
            pagesTraversed: [],
        }
        log(`Snapshot directory: ${ctx.snapshotDir}`)

        log('Navigating to dashboards')
        await page.goto('/dashboards')
        await waitForPageStable(page)
        ctx.pagesTraversed.push('Dashboards list')

        await openFirstDashboard(page, ctx)

        const snapshots = await takeThreeSnapshots(ctx, async () => {
            const filterToggleIterations = 200
            log(`Toggling dashboard filters ${filterToggleIterations} times`)

            for (let i = 0; i < filterToggleIterations; i++) {
                const filterButton = page.locator('.property-filter-row .LemonButton').first()

                if (await filterButton.isVisible({ timeout: 2000 }).catch(() => false)) {
                    log(`Filter toggle iteration ${i + 1}/${filterToggleIterations}`)
                    await filterButton.click()
                    await page.waitForTimeout(150)
                    await filterButton.click()
                    await page.waitForTimeout(150)
                    ctx.pagesTraversed.push(`Filter toggle ${i + 1}`)
                } else {
                    log('Filter button not visible, skipping iteration')
                    break
                }
            }
        })

        const leakResults = await analyzeSnapshots(snapshots.baseline, snapshots.target, snapshots.final)
        generateAndSaveReport(ctx, snapshots, leakResults)

        expect(snapshots.baseline).toBeTruthy()
        expect(snapshots.target).toBeTruthy()
        expect(snapshots.final).toBeTruthy()
    })
})

async function openFirstDashboard(page: Page, ctx: MemoryLeakTestContext): Promise<void> {
    // Wait for dashboard links to appear
    await page.locator('a[href*="/dashboard/"]').first().waitFor({ timeout: 10000 })
    
    const dashboardLinks = await page.locator('a[href*="/dashboard/"]').all()
    log(`Found ${dashboardLinks.length} dashboard links`)

    for (const link of dashboardLinks) {
        const href = await link.getAttribute('href')
        if (href && /\/dashboard\/\d+/.test(href)) {
            log(`Opening dashboard: ${href}`)
            await link.click()
            await waitForPageStable(page)
            await page.waitForTimeout(4000)
            ctx.pagesTraversed.push(`Dashboard: ${href}`)
            return
        }
    }
    
    throw new Error('No valid dashboard found - test environment may not be properly initialized')
}

async function navigateToSqlEditor(page: Page, ctx: MemoryLeakTestContext): Promise<void> {
    log('Navigating to SQL editor')
    const sqlEditorMenu = page.locator('[data-attr="menu-item-sql-editor"]')
    if (!(await sqlEditorMenu.isVisible())) {
        return
    }

    await sqlEditorMenu.click()
    await waitForPageStable(page)
    ctx.pagesTraversed.push('SQL Editor')

    const editor = page.locator('[data-attr="hogql-query-editor"]')
    if (!(await editor.isVisible({ timeout: 5000 }).catch(() => false))) {
        return
    }

    log('Running SQL queries')
    await editor.click()
    await page.waitForTimeout(500)

    const queries = [
        'select * from events limit 10',
        'select * from events limit 100',
        'select count(*) from events',
        'select event, count(*) from events group by event limit 20',
    ]

    for (const query of queries) {
        log(`Running query: ${query.substring(0, 30)}...`)
        await page.keyboard.press('Meta+a')
        await page.keyboard.type(query, { delay: 20 })

        const runButton = page.locator('[data-attr="hogql-query-editor-run-button"]')
        if (await runButton.isVisible().catch(() => false)) {
            await runButton.click()
            await page.waitForTimeout(3000)
        }
        ctx.pagesTraversed.push(`SQL Query: ${query.substring(0, 20)}...`)
    }

    log('Scrolling SQL results')
    await page.evaluate(() => {
        const resultsPane = document.querySelector('.DataTable, [class*="results"]')
        if (resultsPane) {
            resultsPane.scrollTop = resultsPane.scrollHeight
            resultsPane.scrollTop = 0
        }
    })
    await page.waitForTimeout(1000)
}

async function navigateToSessionReplay(page: Page, ctx: MemoryLeakTestContext): Promise<void> {
    log('Navigating to Session Replay')
    const sessionReplayMenu = page.locator('[data-attr="menu-item-replay"]')
    if (!(await sessionReplayMenu.isVisible())) {
        return
    }

    await sessionReplayMenu.click()
    await waitForPageStable(page)
    ctx.pagesTraversed.push('Session Replay')

    await page.keyboard.press('Escape')
    await page.waitForTimeout(1000)

    const recordings = page.locator('[data-attr="select-recording"]')
    const recordingCount = await recordings.count()
    log(`Found ${recordingCount} recordings`)

    if (recordingCount === 0) {
        return
    }

    log('Opening first recording')
    await recordings.first().click()
    await page.waitForTimeout(3000)
    ctx.pagesTraversed.push('Recording 1')

    log('Switching between recordings')
    for (let i = 1; i < Math.min(3, recordingCount); i++) {
        const freshRecordings = page.locator('[data-attr="select-recording"]')
        const recording = freshRecordings.nth(i)
        if (await recording.isVisible().catch(() => false)) {
            await recording.click()
            await page.waitForTimeout(2000)
            ctx.pagesTraversed.push(`Recording ${i + 1}`)
        }
    }
}
