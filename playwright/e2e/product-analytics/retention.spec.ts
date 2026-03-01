import { InsightType } from '~/types'

import { InsightPage } from '../../page-models/insightPage'
import { createEvent, daysAgo } from '../../utils/event-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

const EVENT_NAME = 'retention_test_event'
const user = (n: number): string => `retention-user-${n}`

const events = [
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(6) }).repeat(10),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(5) }).repeat(8),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(4) }).repeat(6),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(3) }).repeat(4),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(2) }).repeat(3),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(1) }).repeat(2),
    ...createEvent({ event: EVENT_NAME, user, timestamp: daysAgo(0) }).repeat(1),
]

const isWeekHeader = (h: string): boolean => /week/i.test(h)
const isDayHeader = (h: string): boolean => /Days?\s+1/.test(h)
const isRangeHeader = (h: string): boolean => /\d+-\d+/.test(h)
const isTooltipLike = (text: string): boolean => /Day|Cohort/.test(text)

test.describe('Retention', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            no_demo_data: true,
            events,
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Retention calculations, period, breakdown, and chart', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a retention insight with our event', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await insight.retention.selectTargetEvent(EVENT_NAME)
            await insight.retention.selectReturningEvent(EVENT_NAME)
        })

        await test.step('verify cohort sizes and retention curve', async () => {
            const sizes = await insight.retention.getCohortSizes()
            // All users first appear on daysAgo(6), so only that cohort has users.
            // Row 0 = 7-days-ago (empty), Row 1 = 6-days-ago (10 users), rest empty.
            expect(sizes[0]).toBe(0)
            expect(sizes[1]).toBe(10)

            const percentages = await insight.retention.getCellPercentages(1)
            expect(percentages).toEqual(['100.0%', '80.0%', '60.0%', '40.0%', '30.0%', '20.0%', '10.0%'])

            // Empty cohorts should show 0%
            const emptyPercentages = await insight.retention.getCellPercentages(0)
            expect(emptyPercentages.every((p) => p === '0.0%')).toBe(true)
        })

        await test.step('change period from Day to Week', async () => {
            await insight.retention.selectPeriod('weeks')
            const headerTexts = await insight.retention.getColumnHeaderTexts()
            expect(headerTexts.filter(isWeekHeader).length).toBe(8)
        })

        await test.step('toggle to cumulative retention', async () => {
            await insight.retention.toggleCumulative()
        })

        await test.step('add breakdown by Browser and verify section header', async () => {
            await insight.retention.addBreakdown('Browser')
            const sectionCount = await insight.retention.sectionHeaders.count()
            expect(sectionCount).toBe(1)
        })

        await test.step('verify line chart renders', async () => {
            await expect(insight.retention.chart).toBeVisible()
            await expect(insight.retention.chart.locator('canvas')).toBeVisible()
        })
    })

    test('Hover tooltips and persons modal', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a retention insight with our event', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await insight.retention.selectTargetEvent(EVENT_NAME)
            await insight.retention.selectReturningEvent(EVENT_NAME)
            await expect(insight.retention.chart.locator('canvas')).toBeVisible()
        })

        await test.step('hover over chart points and verify tooltips', async () => {
            for (const xFraction of [0.15, 0.5]) {
                await insight.retention.hoverChartAt(xFraction, 0.5)
                await expect(insight.retention.tooltip).toBeVisible()
                const text = (await insight.retention.tooltip.textContent()) ?? ''
                expect(isTooltipLike(text)).toBe(true)
                expect(text).not.toContain('NaN')
                expect(text).not.toContain('undefined')
            }
        })

        await test.step('click cohort row and verify persons modal', async () => {
            // Row 1 = 6-days-ago cohort with 10 users
            await insight.retention.clickCohortRow(1)
            const personLinks = insight.retention.personsModal.locator('[data-attr="retention-person-link"]')
            await expect(personLinks.first()).toBeVisible()
            expect(await personLinks.count()).toBe(10)
        })

        await test.step('close modal and verify table is intact', async () => {
            await insight.retention.closePersonsModal()
            await expect(insight.retention.table).toBeVisible()
            expect(await insight.retention.tableRows.count()).toBe(10)
        })
    })

    test('Custom retention brackets', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a retention insight with our event', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await insight.retention.selectTargetEvent(EVENT_NAME)
            await insight.retention.selectReturningEvent(EVENT_NAME)
        })

        await test.step('enable custom brackets [1, 3, 7, 14]', async () => {
            await insight.retention.enableCustomBrackets()
            await insight.retention.setCustomBracket(0, 1)
            await insight.retention.setCustomBracket(1, 3)
            await insight.retention.setCustomBracket(2, 7)
            await insight.retention.addCustomBracket()
            await insight.retention.setCustomBracket(3, 14)
        })

        await test.step('verify custom range headers appear', async () => {
            // Wait for the final API response after all brackets are set (debounce settles)
            // by waiting until we see 3 range headers (one per bracket boundary: 1-3, 3-7, 7-14)
            await expect(async () => {
                const headers = await insight.retention.getColumnHeaderTexts()
                expect(headers.filter(isRangeHeader).length).toBe(3)
            }).toPass({ timeout: 15000 })

            const headerTexts = await insight.retention.getColumnHeaderTexts()
            expect(headerTexts).toContain('Day 0')
            expect(headerTexts.some(isDayHeader)).toBe(true)
            expect(await insight.retention.tableRows.count()).toBe(10)
        })

        await test.step('disable custom brackets and verify default columns return', async () => {
            await insight.retention.disableCustomBrackets()
            expect(await insight.retention.tableHeaders.count()).toBe(10)
        })
    })
})
