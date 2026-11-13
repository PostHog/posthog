import { InsightShortId, InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { createEvent, daysAgo } from '../../../utils/event-data'
import { PlaywrightSetupEvent } from '../../../utils/playwright-setup'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const STEP_1 = 'funnel_step_one'
const STEP_2 = 'funnel_step_two'
const STEP_3 = 'funnel_step_three'

/**
 * Generates funnel events for 20 users across 3 steps with predictable conversion rates.
 *
 *              Step 1    Step 2    Step 3
 *   Chrome      10        10         5      (50% total conversion)
 *   Firefox     10         0         0      (0% total conversion)
 *   Total       20        10         5      (25% total conversion)
 */
function generateFunnelEvents(): PlaywrightSetupEvent[] {
    const chromeUsers = (n: number): string => `chrome-user-${n}`
    const firefoxUsers = (n: number): string => `firefox-user-${n + 10}`

    const chrome = { $browser: 'Chrome' }
    const firefox = { $browser: 'Firefox' }

    return [
        ...createEvent({ event: STEP_1, user: chromeUsers, timestamp: daysAgo(5), properties: chrome }).repeat(10),
        ...createEvent({ event: STEP_1, user: firefoxUsers, timestamp: daysAgo(5), properties: firefox }).repeat(10),
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

    // Setting the conversion window right after navigation or entering edit mode can race
    // the editor's hydration — the edit is occasionally swallowed or reverted by a late
    // insight load. The page model waits for the insight re-fetch, but a just-received
    // response can still apply milliseconds after the edit, so require the dirty state to
    // stick and re-apply if it was reverted.
    async function setConversionWindowUntilDirty(insight: InsightPage, value: string): Promise<void> {
        await expect(async () => {
            await insight.funnels.setConversionWindowInterval(value)
            await expect(insight.saveButton).not.toContainText('No changes', { timeout: 2000 })
            await insight.page.waitForTimeout(300)
            await expect(insight.saveButton).not.toContainText('No changes', { timeout: 500 })
            await expect(insight.saveButton).toBeEnabled({ timeout: 500 })
        }).toPass({ timeout: 30000 })
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
            await expect(insight.funnels.stepValueLabel(1)).toContainText('50')

            const step3 = insight.funnels.stepLegend(2)
            await expect(step3).toContainText('5')
            await expect(step3).toContainText(STEP_3)
            await expect(insight.funnels.stepValueLabel(2)).toContainText('25')
        })

        await test.step('hover funnel bar to show tooltip', async () => {
            await insight.funnels.hoverStepBars()
            await expect(insight.funnels.tooltip.first()).toBeVisible()
        })
    })

    test('Tooltip cleans up when navigating away client-side', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToInsight(seededInsightId())
        await insight.funnels.waitForChart()

        await test.step('hover funnel bar to show tooltip', async () => {
            await insight.funnels.hoverStepBars()
            await expect(insight.funnels.tooltip.first()).toBeVisible()
        })

        await test.step('navigate back via keyboard while the tooltip is shown', async () => {
            // Keyboard navigation keeps the cursor over the canvas, so the tooltip is
            // still shown when the scene unmounts — clicking a link would hide it via
            // hover-away first and make the cleanup assertion below vacuous.
            const insightUrl = page.url()
            const backLink = page.getByLabel(/^Go back to/)
            await backLink.focus()
            await page.keyboard.press('Enter')
            await expect(page).not.toHaveURL(insightUrl)
        })

        await test.step('no orphaned tooltip remains after the scene unmounts', async () => {
            // The tooltip portals to document.body outside the chart's DOM subtree, so
            // it survives scene teardown unless the chart's cleanup actually runs.
            await expect(insight.funnels.tooltip).toHaveCount(0, { timeout: 3000 })
        })
    })

    test('Override/discard lifecycle from dashboard', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboardId = workspace!.created_dashboards![0].id

        await test.step('navigate to insight with filter overrides and verify banner', async () => {
            await insight.goToInsight(seededInsightId(), {
                queryParams: { filters_override: { date_from: '-14d' }, dashboard: dashboardId },
            })
            await expect(page.getByText("a dashboard's filters applied")).toBeVisible({ timeout: 20000 })
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
            await expect(page.getByText("a dashboard's filters applied")).not.toBeVisible()
            await expect(insight.editButton).toBeVisible()
            expect(page.url()).toContain(`dashboard=${dashboardId}`)
        })

        await test.step('edit controls work after discard', async () => {
            await insight.edit()
            await expect(insight.saveButton).toContainText('No changes')

            await setConversionWindowUntilDirty(insight, '3')
            await expect(insight.saveButton).toBeEnabled()
            await expect(insight.saveButton).toContainText('Save')
        })

        await test.step('cancel restores original state after discard flow', async () => {
            await insight.discard()

            await insight.edit()
            await expect(insight.funnels.conversionWindowInput).not.toHaveValue('3')
        })
    })
})
