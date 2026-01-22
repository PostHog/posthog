import { test as base, expect } from '@playwright/test'

import { urls } from 'scenes/urls'

import { ActivityTab } from '~/types'

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

const PAGES_TO_TRAVERSE = [
    { name: 'Home', path: urls.projectHomepage() },
    { name: 'Activity Explorer', path: urls.activity(ActivityTab.ExploreEvents) },
    { name: 'SQL Editor', path: urls.sqlEditor() },
    { name: 'Event Definitions', path: urls.eventDefinitions() },
    { name: 'Project Settings', path: urls.settings('project') },
]

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
    test('detects memory leaks across page navigation', async ({ page }) => {
        test.setTimeout(300000)

        const snapshotDir = createSnapshotDirectory()
        const pagesTraversed: string[] = []
        let baselineSnapshot: HeapSnapshot | null = null
        let targetSnapshot: HeapSnapshot | null = null
        let finalSnapshot: HeapSnapshot | null = null

        await waitForPageStable(page)
        await forceGarbageCollection(page)
        baselineSnapshot = await takeHeapSnapshot(page, snapshotDir, 's1-baseline')
        pagesTraversed.push('Home (baseline)')

        for (const pageInfo of PAGES_TO_TRAVERSE) {
            await page.goto(pageInfo.path)
            await waitForPageStable(page)
            pagesTraversed.push(pageInfo.name)
        }

        await forceGarbageCollection(page)
        targetSnapshot = await takeHeapSnapshot(page, snapshotDir, 's2-target')

        await page.goto(urls.projectHomepage())
        await waitForPageStable(page)
        await forceGarbageCollection(page)
        finalSnapshot = await takeHeapSnapshot(page, snapshotDir, 's3-final')

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

        saveReport(report, snapshotDir)
        generateReport(report)

        expect(baselineSnapshot).toBeTruthy()
        expect(targetSnapshot).toBeTruthy()
        expect(finalSnapshot).toBeTruthy()
    })
})
