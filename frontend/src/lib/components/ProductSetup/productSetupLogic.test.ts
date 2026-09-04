import { expectLogic } from 'kea-test-utils'

import { SetupTaskId } from 'lib/components/ProductSetup'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ActivationTaskStatus, TeamType } from '~/types'

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
})
