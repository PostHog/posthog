import { api } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivationTaskStatus, TeamType } from '~/types'

import { globalSetupLogic } from './globalSetupLogic'
import { productSetupLogic } from './productSetupLogic'
import type { SetupTaskWithState } from './types'

describe('productSetupLogic', () => {
    let logic: ReturnType<typeof productSetupLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        logic = productSetupLogic({ productKey: ProductKey.PRODUCT_ANALYTICS })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    const task = (id: SetupTaskId): SetupTaskWithState =>
        logic.values.tasksWithState.find((t) => t.id === id) as SetupTaskWithState

    const setTeam = async (overrides: Partial<TeamType>): Promise<void> => {
        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess({
                ...teamLogic.values.currentTeam!,
                onboarding_tasks: {},
                ...overrides,
            } as TeamType)
        ).toFinishAllListeners()
    }

    // The reported bug: the install page reads `ingested_event`, so the checklist must too.
    // Without auto-completion, `ingest_first_event` never completes and locks all seven dependents.
    it('auto-completes ingest_first_event from ingested_event and unlocks its dependents', async () => {
        await setTeam({ ingested_event: true, onboarding_tasks: {} })

        expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(true)
        expect(task(SetupTaskId.CreateFirstInsight).lockedReason).toBeUndefined()
    })

    // Guards the default: no event and no saved status keeps the gate closed.
    it('locks a dependent while its dependency is unmet', async () => {
        await setTeam({ ingested_event: false, onboarding_tasks: {} })

        expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(false)
        expect(task(SetupTaskId.CreateFirstInsight).lockedReason).toContain('Ingest your first event')
    })

    // The reported bug: the highlight used to outlive the route that asked for it, so the pulse
    // landed on whatever matched the selector on a page the user opened later.
    it('drops a pending highlight when the user navigates away', async () => {
        await expectLogic(logic, () => logic.actions.runTask(SetupTaskId.CreateFirstInsight)).toFinishAllListeners()

        expect(globalSetupLogic.values.highlight).toEqual({
            selector: '[data-attr="saved-insights-new-insight-button"]',
            // getUrl() is project-relative, so the binding reads the route the router landed on
            pathname: expect.stringContaining(urls.insights()),
        })

        router.actions.push(urls.featureFlag('new'))

        expect(globalSetupLogic.values.highlight).toBeNull()
    })

    // Staying put must not drop the highlight - a query string change is still the same page.
    it('keeps a pending highlight while the route stays the same', async () => {
        await expectLogic(logic, () => logic.actions.runTask(SetupTaskId.CreateFirstInsight)).toFinishAllListeners()

        router.actions.push(router.values.location.pathname, { tab: 'yours' })

        expect(globalSetupLogic.values.highlight).not.toBeNull()
    })

    // A task with no target selector used to leave the previous pulse polling, because nothing
    // cleared it and a docs task never changes the route.
    it('drops a pending highlight when a task without a target selector runs', async () => {
        jest.spyOn(window, 'open').mockReturnValue(null)
        await expectLogic(logic, () => logic.actions.runTask(SetupTaskId.CreateFirstInsight)).toFinishAllListeners()
        expect(globalSetupLogic.values.highlight).not.toBeNull()

        await expectLogic(logic, () => logic.actions.runTask(SetupTaskId.UsePosthogMcp)).toFinishAllListeners()

        expect(globalSetupLogic.values.highlight).toBeNull()
    })

    // A skipped dependency counts as satisfied — skipping used to leave dependents locked forever.
    it('treats a skipped dependency as satisfied', async () => {
        await setTeam({
            ingested_event: false,
            onboarding_tasks: { [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.SKIPPED },
        })

        expect(task(SetupTaskId.IngestFirstEvent).skipped).toBe(true)
        expect(task(SetupTaskId.CreateFirstInsight).lockedReason).toBeUndefined()
    })

    // A dependency completed the normal way (saved status) still unlocks dependents.
    it('unlocks a dependent when its dependency is saved as completed', async () => {
        await setTeam({
            ingested_event: false,
            onboarding_tasks: { [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.COMPLETED },
        })

        expect(task(SetupTaskId.CreateFirstInsight).lockedReason).toBeUndefined()
    })

    // A skipped task that later auto-completes must count once, not as both completed and skipped.
    it('does not double-count a skipped task that later auto-completes', async () => {
        await setTeam({
            ingested_event: true,
            onboarding_tasks: { [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.SKIPPED },
        })

        expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(true)
        expect(task(SetupTaskId.IngestFirstEvent).skipped).toBe(false)
        expect(logic.values.completedCount).toBe(logic.values.completedTasks.length)
    })

    // AI observability's ViewFirstTrace/TrackCosts depend on ingest_first_event, which is not one of that
    // product's own tasks. The dependency must still gate and unlock them.
    it('resolves a dependency that lives outside the product task list', async () => {
        const aiLogic = productSetupLogic({ productKey: ProductKey.AI_OBSERVABILITY })
        aiLogic.mount()
        const aiTask = (id: SetupTaskId): SetupTaskWithState =>
            aiLogic.values.tasksWithState.find((t) => t.id === id) as SetupTaskWithState
        try {
            // Unmet: no event and no saved status keeps the dependents locked.
            await setTeam({ ingested_event: false, onboarding_tasks: {} })
            expect(aiTask(SetupTaskId.ViewFirstTrace).lockedReason).not.toBeUndefined()

            // A saved COMPLETED unlocks even though ingest_first_event is not in this product's list.
            await setTeam({
                ingested_event: false,
                onboarding_tasks: { [SetupTaskId.IngestFirstEvent]: ActivationTaskStatus.COMPLETED },
            })
            expect(aiTask(SetupTaskId.ViewFirstTrace).lockedReason).toBeUndefined()

            // The ingested_event auto-completion also reaches it.
            await setTeam({ ingested_event: true, onboarding_tasks: {} })
            expect(aiTask(SetupTaskId.TrackCosts).lockedReason).toBeUndefined()
        } finally {
            aiLogic.unmount()
        }
    })

    describe('a task the user checks, unchecks and re-checks', () => {
        const flushPromises = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

        const holdTeamUpdate = (): { resolve: (team: unknown) => void; reject: (error: Error) => void } => {
            const handle = { resolve: (_team: unknown) => {}, reject: (_error: Error) => {} }
            jest.spyOn(api, 'update').mockImplementation(
                () =>
                    new Promise((resolve, reject) => {
                        handle.resolve = resolve
                        handle.reject = reject
                    })
            )
            return handle
        }

        // The reported bug: the guard read the saved team state while the overlay already showed the
        // task as unchecked, so a re-check before the save landed did nothing however often it was clicked.
        it('re-checks while the uncheck is still saving', async () => {
            holdTeamUpdate()
            await setTeam({
                ingested_event: true,
                onboarding_tasks: { [SetupTaskId.CreateFirstInsight]: ActivationTaskStatus.COMPLETED },
            })

            logic.actions.unmarkTaskAsCompleted(SetupTaskId.CreateFirstInsight)
            await flushPromises()
            expect(task(SetupTaskId.CreateFirstInsight).completed).toBe(false)

            logic.actions.markTaskAsCompleted(SetupTaskId.CreateFirstInsight, true)
            await flushPromises()

            expect(task(SetupTaskId.CreateFirstInsight).completed).toBe(true)
        })

        // The reported bug: an unchecked task that a team flag also proves done came straight back,
        // so the count recovered on its own and the user could not uncheck the task at all.
        it('keeps an auto-completed task unchecked after the user unchecks it', async () => {
            holdTeamUpdate()
            await setTeam({ ingested_event: true, onboarding_tasks: {} })
            expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(true)

            logic.actions.unmarkTaskAsCompleted(SetupTaskId.IngestFirstEvent)
            await flushPromises()
            expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(false)

            // An auto-completion from elsewhere in the app must not put the checkmark back.
            logic.actions.markTaskAsCompleted(SetupTaskId.IngestFirstEvent)
            await flushPromises()

            expect(task(SetupTaskId.IngestFirstEvent).completed).toBe(false)
        })

        // The overlay used to outlive its save, so the checklist stayed on a value the team had moved on from.
        it('hands the task back to the saved state once the save lands', async () => {
            const update = holdTeamUpdate()
            await setTeam({ ingested_event: true, onboarding_tasks: {} })

            logic.actions.markTaskAsCompleted(SetupTaskId.CreateFirstInsight, true)
            await flushPromises()
            update.resolve({
                ...teamLogic.values.currentTeam,
                onboarding_tasks: { [SetupTaskId.CreateFirstInsight]: ActivationTaskStatus.COMPLETED },
            })
            await flushPromises()

            expect(globalSetupLogic.values.optimisticTaskStatuses[SetupTaskId.CreateFirstInsight]).toBeUndefined()
            expect(task(SetupTaskId.CreateFirstInsight).completed).toBe(true)
        })

        // A save that fails must not leave a checkmark that exists nowhere.
        it('rolls the checkmark back when the save fails', async () => {
            const update = holdTeamUpdate()
            await setTeam({ ingested_event: true, onboarding_tasks: {} })

            logic.actions.markTaskAsCompleted(SetupTaskId.CreateFirstInsight, true)
            await flushPromises()
            expect(task(SetupTaskId.CreateFirstInsight).completed).toBe(true)

            update.reject(new Error('team update failed'))
            await flushPromises()

            expect(task(SetupTaskId.CreateFirstInsight).completed).toBe(false)
        })
    })
})
