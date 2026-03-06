import { InsightShortId, InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { randomString } from '../../../utils'
import { createEvent, daysAgo } from '../../../utils/event-data'
import { PlaywrightSetupEvent } from '../../../utils/playwright-setup'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const STEP_1 = 'funnel_step_one'
const STEP_2 = 'funnel_step_two'
const STEP_3 = 'funnel_step_three'
const EXCLUSION_EVENT = 'funnel_excluded_action'

/**
 * Generates funnel events for 20 users across 3 steps with predictable conversion rates.
 *
 *              Step 1    Step 2    Step 3
 *   Chrome      10        10         5      (50% total conversion)
 *   Firefox     10         0         0      (0% total conversion)
 *   Total       20        10         5      (25% total conversion)
 *
 * chrome-user-0 performs the exclusion event between steps 1 and 2.
 * This user converts through all 3 steps, so excluding them meaningfully
 * changes the numbers: 20→19 at step 1, 10→9 at step 2, 5→4 at step 3.
 * Steps are spaced 24h apart so a 1-hour conversion window yields 0 conversions.
 */
function generateFunnelEvents(): PlaywrightSetupEvent[] {
    const chromeUsers = (n: number): string => `chrome-user-${n}`
    const firefoxUsers = (n: number): string => `firefox-user-${n + 10}`

    const chrome = { $browser: 'Chrome', $session_id: 'chrome-session' }
    const firefox = { $browser: 'Firefox', $session_id: 'firefox-session' }

    // Midpoint between step 1 and step 2 — immune to time-of-day drift
    const betweenStep1And2 = (() => {
        const d = new Date()
        d.setDate(d.getDate() - 5)
        d.setHours(12, 0, 0, 0)
        return d.toISOString()
    })()

    return [
        ...createEvent({ event: STEP_1, user: chromeUsers, timestamp: daysAgo(5), properties: chrome }).repeat(10),
        ...createEvent({ event: STEP_1, user: firefoxUsers, timestamp: daysAgo(5), properties: firefox }).repeat(10),
        ...createEvent({
            event: EXCLUSION_EVENT,
            user: 'chrome-user-0',
            timestamp: betweenStep1And2,
            properties: chrome,
        }).events,
        ...createEvent({ event: STEP_2, user: chromeUsers, timestamp: daysAgo(4), properties: chrome }).repeat(10),
        ...createEvent({ event: STEP_3, user: chromeUsers, timestamp: daysAgo(3), properties: chrome }).repeat(5),
    ]
}

const FUNNEL_QUERY = {
    kind: 'InsightVizNode',
    source: {
        kind: 'FunnelsQuery',
        series: [
            { kind: 'EventsNode', event: STEP_1 },
            { kind: 'EventsNode', event: STEP_2 },
            { kind: 'EventsNode', event: STEP_3 },
        ],
        dateRange: { date_from: '-7d' },
        funnelsFilter: { funnelVizType: 'steps' },
    },
}

test.describe('Funnel insights', () => {
    test.setTimeout(60_000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            events: generateFunnelEvents(),
            insights: [{ name: 'Seeded Funnel', query: FUNNEL_QUERY }],
            dashboards: [{ name: 'Funnel Dashboard', insight_indexes: [0] }],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    function seededInsightId(): InsightShortId {
        return workspace!.created_insights![0].short_id as InsightShortId
    }

    async function goToSeededFunnel(page: InsightPage['page']): Promise<InsightPage> {
        const insight = new InsightPage(page)
        await insight.goToInsight(seededInsightId(), { edit: true })
        await insight.funnels.waitForChart()
        return insight
    }

    test('Create funnel via UI and verify conversion math and tooltips', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a 3-step funnel from scratch', async () => {
            await insight.goToNewInsight(InsightType.FUNNELS)
            await expect(insight.activeTab).toContainText('Funnels')

            await insight.funnels.selectStepEvent(0, STEP_1)
            await page.getByRole('button', { name: 'Add step' }).click()
            await page.keyboard.press('Escape')
            await insight.funnels.selectStepEvent(1, STEP_2)
            await page.getByRole('button', { name: 'Add step' }).click()
            await page.keyboard.press('Escape')
            await insight.funnels.selectStepEvent(2, STEP_3)
            await insight.funnels.waitForChart()
        })

        await test.step('verify step counts and conversion rates', async () => {
            const step1 = insight.funnels.stepLegend(0)
            await expect(step1).toContainText('20')
            await expect(step1).toContainText(STEP_1)

            const step2 = insight.funnels.stepLegend(1)
            await expect(step2).toContainText('10')
            await expect(step2).toContainText(STEP_2)
            await expect(step2).toContainText('50')

            const step3 = insight.funnels.stepLegend(2)
            await expect(step3).toContainText('5')
            await expect(step3).toContainText(STEP_3)
            await expect(step3).toContainText('25')
        })

        await test.step('hover funnel bar to show tooltip', async () => {
            const stepBar = insight.funnels.verticalChart.getByTestId('funnel-step-bar').first()
            await stepBar.hover()
            await expect(insight.funnels.tooltip.first()).toBeVisible()
        })
    })

    test('Switch between funnel visualization types', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('default is Conversion steps with correct counts', async () => {
            await expect(insight.funnels.verticalChart).toBeVisible()
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
            await expect(insight.funnels.stepLegend(2)).toContainText('5')
        })

        await test.step('switch to Time to convert', async () => {
            await insight.funnels.selectVizType('Time to convert')
            await insight.funnels.waitForHistogram()
            await expect(insight.funnels.verticalChart).not.toBeVisible()
        })

        await test.step('switch to Historical trends', async () => {
            await insight.funnels.selectVizType('Historical trends')
            await insight.funnels.waitForTrendsLineGraph()
            await expect(insight.funnels.histogram).not.toBeVisible()
        })

        await test.step('switch back to Conversion steps and verify counts preserved', async () => {
            await insight.funnels.selectVizType('Conversion steps')
            await insight.funnels.waitForChart()
            await expect(insight.funnels.trendsLineGraph).not.toBeVisible()
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
            await expect(insight.funnels.stepLegend(2)).toContainText('5')
        })
    })

    test('Change funnel layout between left-to-right and top-to-bottom', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('default is left-to-right (vertical bars)', async () => {
            await expect(insight.funnels.verticalChart).toBeVisible()
        })

        await test.step('switch to top-to-bottom layout', async () => {
            await insight.funnels.selectLayout('Top to bottom')
            await expect(insight.funnels.horizontalChart).toBeVisible()
            await expect(insight.funnels.verticalChart).not.toBeVisible()
        })

        await test.step('switch back to left-to-right layout', async () => {
            await insight.funnels.selectLayout('Left to right')
            await expect(insight.funnels.verticalChart).toBeVisible()
            await expect(insight.funnels.horizontalChart).not.toBeVisible()
        })
    })

    test('Configure step ordering and session aggregation gating', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('default step order is Sequential', async () => {
            await expect(insight.funnels.stepOrderFilter).toContainText('Sequential')
        })

        await test.step('switch to Strict order and verify counts', async () => {
            await insight.funnels.selectStepOrder('Strict order')
            await insight.funnels.waitForChart()
            await expect(insight.funnels.stepOrderFilter).toContainText('Strict')
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('9')
            await expect(insight.funnels.stepLegend(2)).toContainText('4')
        })

        await test.step('switch to Any order and verify counts', async () => {
            await insight.funnels.selectStepOrder('Any order')
            await insight.funnels.waitForChart()
            await expect(insight.funnels.stepOrderFilter).toContainText('Any order')
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
            await expect(insight.funnels.stepLegend(2)).toContainText('5')
        })

        await test.step('switch back to Sequential', async () => {
            await insight.funnels.selectStepOrder('Sequential')
            await insight.funnels.waitForChart()
        })

        await test.step('clicking dropped-off count opens persons modal with correct users', async () => {
            await insight.save()
            await insight.funnels.waitForChart()

            const step2 = insight.funnels.stepLegend(1)
            const droppedOffButton = step2.getByTestId('funnel-inspect-dropped-off')
            await droppedOffButton.click()

            const modal = page.getByTestId('persons-modal')
            await expect(modal).toBeVisible({ timeout: 10000 })
            await expect(modal).toContainText('firefox-user-1')

            await modal.getByRole('button', { name: 'close' }).click()
            await expect(modal).not.toBeVisible()
        })

        await test.step('session aggregation allows opening sessions modal on step counts', async () => {
            await insight.edit()
            await insight.funnels.selectAggregation('Unique sessions')
            await insight.funnels.waitForChart()
            await insight.save()
            await insight.funnels.waitForChart()

            const step2 = insight.funnels.stepLegend(1)
            await expect(step2).toBeVisible()

            await expect(step2.getByTestId('funnel-inspect-converted')).toHaveCount(1)
            await expect(step2.getByTestId('funnel-inspect-dropped-off')).toHaveCount(1)

            const droppedOffButton = step2.getByTestId('funnel-inspect-dropped-off')
            await droppedOffButton.click()

            const modal = page.getByTestId('persons-modal')
            await expect(modal).toBeVisible({ timeout: 10000 })

            await modal.getByRole('button', { name: 'close' }).click()
            await expect(modal).not.toBeVisible()
        })

        await test.step('revert seeded insight to unique users', async () => {
            await insight.edit()
            await insight.funnels.selectAggregation('Unique users')
            await insight.funnels.waitForChart()
            await insight.save()
        })
    })

    test('Change conversion window', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('verify baseline counts with default 14-day window', async () => {
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
        })

        await test.step('set conversion window to 1 hour — step 2 drops to 0', async () => {
            await insight.funnels.setConversionWindowInterval('1')
            await insight.funnels.selectConversionWindowUnit('Hour')
            await insight.funnels.waitForChart()

            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('0')
        })

        await test.step('set conversion window back to 14 days — original numbers return', async () => {
            await insight.funnels.setConversionWindowInterval('14')
            await insight.funnels.selectConversionWindowUnit('Day')
            await insight.funnels.waitForChart()

            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
        })
    })

    test('Add breakdown and verify steps table', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('add breakdown by $browser', async () => {
            await insight.funnels.addBreakdown('$browser')
            await insight.funnels.waitForChart()
        })

        await test.step('verify breakdown table shows Chrome and Firefox', async () => {
            const table = page.getByTestId('funnel-breakdown-table')
            await expect(table).toBeVisible()
            await expect(table.getByText('Chrome')).toBeVisible()
            await expect(table.getByText('Firefox')).toBeVisible()
        })

        await test.step('verify Chrome: 50% total conversion (5/10)', async () => {
            const table = page.getByTestId('funnel-breakdown-table')
            const chromeRow = table.getByRole('row').filter({ hasText: 'Chrome' })
            await expect(chromeRow).toContainText('50')
        })

        await test.step('verify Firefox: 0% total conversion (0/10)', async () => {
            const table = page.getByTestId('funnel-breakdown-table')
            const firefoxRow = table.getByRole('row').filter({ hasText: 'Firefox' })
            await expect(firefoxRow).toContainText('0%')
        })
    })

    test('Exclusion steps filter out users', async ({ page }) => {
        const insight = await goToSeededFunnel(page)

        await test.step('verify baseline: 20 → 10 → 5', async () => {
            await expect(insight.funnels.stepLegend(0)).toContainText('20')
            await expect(insight.funnels.stepLegend(1)).toContainText('10')
        })

        await test.step('add exclusion for funnel_excluded_action between steps 1 and 2', async () => {
            await insight.funnels.addExclusion(EXCLUSION_EVENT)
            await insight.funnels.waitForChart()
        })

        await test.step('verify chrome-user-0 is excluded: 19 → 9 → 4', async () => {
            await expect(insight.funnels.stepLegend(0)).toContainText('19')
            await expect(insight.funnels.stepLegend(1)).toContainText('9')
            await expect(insight.funnels.stepLegend(2)).toContainText('4')
        })
    })

    test('Save, button states, edit, and cancel lifecycle', async ({ page }) => {
        const insight = await goToSeededFunnel(page)
        const funnelName = randomString('funnel-lifecycle')

        await test.step('save button is enabled on unsaved changes', async () => {
            await insight.funnels.setConversionWindowInterval('7')
            await insight.funnels.waitForChart()
            await expect(insight.saveButton).toBeEnabled()
            await expect(insight.saveButton).not.toContainText('No changes')
        })

        await test.step('name and save the insight', async () => {
            await insight.editName(funnelName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('click edit — save button shows No changes when clean', async () => {
            await insight.edit()
            await expect(insight.saveButton).toContainText('No changes')
            await expect(insight.saveButton).toBeDisabled()
        })

        await test.step('make a change — save enables, cancel button appears', async () => {
            await insight.funnels.setConversionWindowInterval('3')
            await insight.funnels.waitForChart()

            await expect(insight.saveButton).toBeEnabled()
            await expect(insight.saveButton).toContainText('Save')
            await expect(insight.cancelButton).toBeVisible()
        })

        await test.step('cancel edit — conversion window reverts to saved value', async () => {
            await insight.cancelButton.click()
            await expect(insight.editButton).toBeVisible()
            await insight.funnels.waitForChart()

            await insight.edit()
            await expect(insight.funnels.conversionWindowInput).toHaveValue('7')
        })
    })

    test('Override/discard lifecycle from dashboard', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboardId = workspace!.created_dashboards![0].id

        await test.step('navigate to insight with filter overrides and verify banner', async () => {
            await insight.goToInsight(seededInsightId(), {
                queryParams: { filters_override: { date_from: '-14d' }, dashboard: dashboardId },
            })
            await expect(page.getByText('filter/variable overrides')).toBeVisible({ timeout: 20000 })
            await expect(
                page
                    .getByRole('button', { name: 'Discard overrides' })
                    .or(page.getByRole('link', { name: 'Discard overrides' }))
            ).toBeVisible()
        })

        await test.step('discard overrides removes the banner', async () => {
            await page
                .getByRole('button', { name: 'Discard overrides' })
                .or(page.getByRole('link', { name: 'Discard overrides' }))
                .click()
            await expect(page.getByText('filter/variable overrides')).not.toBeVisible()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('edit controls work after discard', async () => {
            await insight.edit()
            await expect(insight.saveButton).toContainText('No changes')

            await insight.funnels.setConversionWindowInterval('3')
            await expect(insight.saveButton).toBeEnabled()
            await expect(insight.saveButton).toContainText('Save')
        })

        await test.step('cancel restores original state after discard flow', async () => {
            await insight.cancelButton.click()
            await expect(insight.editButton).toBeVisible()

            await insight.edit()
            await expect(insight.funnels.conversionWindowInput).not.toHaveValue('3')
        })
    })
})
