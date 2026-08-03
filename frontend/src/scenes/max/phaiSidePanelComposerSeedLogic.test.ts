import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { taskTrackerSceneLogic } from 'products/posthog_ai/frontend/scenes/TaskTracker/taskTrackerSceneLogic'

import { phaiSidePanelComposerSeedLogic } from './phaiSidePanelComposerSeedLogic'

describe('phaiSidePanelComposerSeedLogic', () => {
    let seedLogic: ReturnType<typeof phaiSidePanelComposerSeedLogic.build>
    let trackerLogic: ReturnType<typeof taskTrackerSceneLogic.build>
    let createCount: number
    let runCount: number

    // No hook calls in here (rules-of-hooks) — mocks are set up in beforeEach / the test bodies.
    const mountPanelLogics = (): void => {
        sidePanelStateLogic.mount()
        trackerLogic = taskTrackerSceneLogic({ panelId: 'max-side-panel' })
        trackerLogic.mount()
        seedLogic = phaiSidePanelComposerSeedLogic({ panelId: 'max-side-panel' })
        seedLogic.mount()
    }

    beforeEach(() => {
        createCount = 0
        runCount = 0
        useMocks({
            get: {
                '/api/projects/:team/tasks/': { results: [], count: 0 },
                '/api/projects/:team/tasks/repositories/': { repositories: [] },
                '/api/environments/:team/integrations/': { results: [] },
            },
            post: {
                '/api/projects/:team/tasks/': async ({ request }) => {
                    createCount++
                    return [200, { id: 'new-task', ...((await request.json()) as Record<string, any>) }]
                },
                '/api/projects/:team/tasks/:id/run/': () => {
                    runCount++
                    return [200, { id: 'new-task' }]
                },
            },
        })
    })

    afterEach(() => {
        seedLogic?.unmount()
        trackerLogic?.unmount()
    })

    // The org-level AI data-processing consent gate: an auto-run CTA (`!`-prefixed prompt) must never start
    // an agent run before the org approved AI data processing — the legacy path blocks this in `askMax`, and
    // dropping the `dataProcessingAccepted` check in the seed bridge would silently ship unconsented sandbox
    // runs (the tasks backend has no server-side consent check).
    it('holds an auto-run seed as prefill and sends no task create/run when consent is missing', async () => {
        useMocks({
            get: {
                // The org bootstrapped via app context below gets re-fetched on organizationLogic mount —
                // keep the API in agreement so a late load can't flip the consent value mid-test.
                '/api/organizations/@current/': () => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: false },
                ],
            },
        })
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: false,
        })
        mountPanelLogics()

        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, '!Foo bar')
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createCount).toBe(0)
        expect(runCount).toBe(0)
        // The prompt is retained as a prefill so consent approval doesn't lose it; nothing was submitted.
        expect(trackerLogic.values.newTaskData.description).toBe('Foo bar')
        expect(trackerLogic.values.activeCreation).toBeNull()
    })

    // Control for the test above: with consent accepted the same CTA must create and run the task — proving
    // the no-request assertion holds because of the gate, not because the bridge stopped forwarding seeds
    // altogether. The org is passed explicitly since app context persists across tests in this file.
    it('auto-submits an auto-run seed when consent is accepted', async () => {
        initKeaTests(true, undefined, undefined, {
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: true,
        })
        mountPanelLogics()

        sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, '!Foo bar')
        await expectLogic(trackerLogic).toFinishAllListeners()

        expect(createCount).toBe(1)
        expect(runCount).toBe(1)
        expect(trackerLogic.values.activeCreation).toMatchObject({ taskId: 'new-task' })
    })
})
