import { InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { PathNode } from '../../../page-models/insights/pathsInsight'
import { randomString } from '../../../utils'
import { sequentialCustomEvents, sequentialPageviews } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const events = [...sequentialPageviews.events, ...sequentialCustomEvents.events]

function expectNodesToMatch(actual: PathNode[], expected: { name: string; count: number }[]): void {
    for (const exp of expected) {
        const match = actual.find((n) => n.name === exp.name)
        expect(match, `expected node containing "${exp.name}"`).toBeDefined()
        expect(match!.count, `count for "${exp.name}"`).toBe(exp.count)
    }
}

test.describe('User Paths insights', () => {
    test.setTimeout(60_000)
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

    test('Create paths insight, verify node counts, change steps, save and reload', async ({ page }) => {
        const insight = new InsightPage(page)
        const name = randomString('paths')

        await test.step('navigate to new Paths insight and verify tab', async () => {
            await insight.goToNewInsight(InsightType.PATHS)
            await expect(insight.activeTab).toContainText('User Paths')
            await insight.paths.waitForNodes()
        })

        await test.step('verify path nodes match seeded pageview data', async () => {
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialPageviews.expected.nodes)
        })

        await test.step('change step count to 3 and verify fewer nodes', async () => {
            await insight.paths.selectSteps(3)
            await insight.paths.waitForNodes()
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialPageviews.expected.nodes.slice(0, 3))
            const signupNode = nodes.find((n) => n.name === '/signup')
            expect(signupNode, '/signup should not appear with 3 steps').toBeUndefined()
        })

        await test.step('name and save the insight', async () => {
            await insight.editName(name)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('reload and verify step count and node data persisted', async () => {
            await page.reload({ waitUntil: 'domcontentloaded' })
            await insight.paths.waitForNodes()
            await expect(insight.editButton).toBeVisible()
            await expect(insight.paths.stepsButton).toContainText('3 Steps')
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialPageviews.expected.nodes.slice(0, 3))
        })
    })

    test('Switch to custom events and verify node counts match seeded data', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Paths insight with pageview data', async () => {
            await insight.goToNewInsight(InsightType.PATHS)
            await expect(insight.activeTab).toContainText('User Paths')
            await insight.paths.waitForNodes()
        })

        await test.step('verify initial pageview nodes', async () => {
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialPageviews.expected.nodes)
        })

        await test.step('switch to Custom event and verify custom event nodes', async () => {
            await insight.paths.selectEventType('Custom event')
            await insight.paths.waitForNodes()
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialCustomEvents.expected.nodes)
        })

        await test.step('switch back to Page views and verify pageview nodes return', async () => {
            await insight.paths.selectEventType('Page views')
            await insight.paths.waitForNodes()
            const nodes = await insight.paths.getNodes()
            expectNodesToMatch(nodes, sequentialPageviews.expected.nodes)
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })
})
