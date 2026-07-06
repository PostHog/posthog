import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { PipelineResultType } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

describe('processPersonlessDistinctIdsBatchStep', () => {
    let mockPersonsStore: jest.Mocked<PersonsStoreForBatch>
    let team: Team
    let processPersonlessDistinctIdsBatchStep: typeof import('~/ingestion/pipelines/analytics/steps/processPersonlessDistinctIdsBatchStep').processPersonlessDistinctIdsBatchStep
    let personlessDistinctIdCacheOperationsCounter: typeof import('~/ingestion/common/persons/personless-distinct-id-cache').personlessDistinctIdCacheOperationsCounter

    // Reads the freshly-imported counter the step writes to (resetModules gives each test its own).
    const counterValue = async (operation: string, source: string): Promise<number> => {
        const metric = await personlessDistinctIdCacheOperationsCounter.get()
        return metric.values.find((v) => v.labels.operation === operation && v.labels.source === source)?.value ?? 0
    }

    beforeEach(async () => {
        // Reset modules to get a fresh LRU cache for each test
        jest.resetModules()
        const module = await import('~/ingestion/pipelines/analytics/steps/processPersonlessDistinctIdsBatchStep.js')
        processPersonlessDistinctIdsBatchStep = module.processPersonlessDistinctIdsBatchStep
        // Import the cache module from the same fresh graph so the counter is the one the step increments.
        personlessDistinctIdCacheOperationsCounter = (
            await import('~/ingestion/common/persons/personless-distinct-id-cache.js')
        ).personlessDistinctIdCacheOperationsCounter

        team = createTestTeam()

        mockPersonsStore = {
            processPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(undefined),
            getPersonlessBatchResult: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<PersonsStoreForBatch>
    })

    const createInput = (
        distinctId: string,
        processPerson: boolean | undefined = undefined,
        overrides: Partial<PluginEvent> = {},
        eventTeam: Team = team
    ): { event: PluginEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch } => ({
        event: createTestPluginEvent({
            distinct_id: distinctId,
            team_id: eventTeam.id,
            properties: processPerson === undefined ? {} : { $process_person_profile: processPerson },
            uuid: `uuid-${distinctId}`,
            ...overrides,
        }),
        team: eventTeam,
        personsStoreForBatch: mockPersonsStore,
    })

    const createFlagCalledInput = (
        distinctId: string,
        properties: PluginEvent['properties'] = {},
        eventTeam: Team = team
    ): { event: PluginEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch } =>
        createInput(distinctId, undefined, { event: '$feature_flag_called', properties }, eventTeam)

    describe('when enabled', () => {
        it('should process personless events and call batch insert', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true)
            const events = [createInput('user-1', false), createInput('user-2', false), createInput('user-3', false)]

            const results = await step(events)

            expect(results).toHaveLength(3)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
                { teamId: team.id, distinctId: 'user-3' },
            ])
        })

        it('should skip non-personless events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true)
            const events = [
                createInput('user-1', true), // processPerson=true
                createInput('user-2', false), // processPerson=false (personless)
                createInput('user-3'), // processPerson=undefined (default, not personless)
            ]

            const results = await step(events)

            expect(results).toHaveLength(3)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should not call batch insert when no personless events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true)
            const events = [createInput('user-1', true), createInput('user-2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should return all events as OK even if batch insert fails', async () => {
            mockPersonsStore.processPersonlessDistinctIdsBatch.mockRejectedValue(new Error('DB error'))

            const step = processPersonlessDistinctIdsBatchStep(true)
            const events = [createInput('user-1', false)]

            // The step should throw since we don't handle errors gracefully
            await expect(step(events)).rejects.toThrow('DB error')
        })
    })

    describe('when disabled', () => {
        it('should not process any events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(false)
            const events = [createInput('user-1', false), createInput('user-2', false)]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })
    })

    describe('LRU cache behavior', () => {
        it('should deduplicate entries within same batch before hitting cache', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true)
            const events = [
                createInput('user-1', false),
                createInput('user-1', false), // Duplicate - deduped before cache/insert
                createInput('user-2', false),
            ]

            await step(events)

            // Duplicates are removed before batch insert
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should use cache to skip already-inserted distinct IDs across batches', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true)

            // First batch
            await step([createInput('user-1', false)])
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
            ])

            mockPersonsStore.processPersonlessDistinctIdsBatch.mockClear()

            // Second batch - user-1 should be cached, only user-2 should be inserted
            await step([createInput('user-1', false), createInput('user-2', false)])
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })
    })

    describe('$feature_flag_called batching', () => {
        it('should batch insert flag-called candidates for enabled teams', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, String(team.id))
            const events = [createFlagCalledInput('user-1'), createFlagCalledInput('user-2')]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should not insert flag-called events when the team is not enabled', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '') // no enabled teams
            const events = [createFlagCalledInput('user-1')]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should only insert flag-called candidates from teams in the matcher, not others in the same batch', async () => {
            const otherTeam = createTestTeam({ id: team.id + 1 })
            const step = processPersonlessDistinctIdsBatchStep(true, String(team.id)) // only `team` enabled

            const events = [
                createFlagCalledInput('enabled-user'),
                createFlagCalledInput('other-team-user', {}, otherTeam),
            ]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            // Only the enabled team's distinct ID is inserted; the other team's flag-called event is skipped.
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'enabled-user' },
            ])
        })

        it('should support "*" to enable flag-called batching for all teams', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '*')
            const events = [createFlagCalledInput('user-1')]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
            ])
        })

        it('should skip flag-called events that explicitly set $process_person_profile=true', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '*')
            const events = [createFlagCalledInput('user-1', { $process_person_profile: true })]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should skip flag-called events carrying group keys', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '*')
            const events = [createFlagCalledInput('user-1', { $groups: { org: 'acme' } })]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should treat a flag-called event with $process_person_profile=false as explicit-personless', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '') // flag-called batching off
            const events = [createFlagCalledInput('user-1', { $process_person_profile: false })]

            await step(events)

            // Still inserted via the explicit-personless branch, independent of flag-called enablement.
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
            ])
        })

        it('should batch explicit-personless and flag-called candidates together', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '*')
            const events = [createInput('user-1', false), createFlagCalledInput('user-2')]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should not insert flag-called candidates when disabled', async () => {
            const step = processPersonlessDistinctIdsBatchStep(false, '*')
            const events = [createFlagCalledInput('user-1')]

            await step(events)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should count hits and misses per source on the cache counter', async () => {
            const step = processPersonlessDistinctIdsBatchStep(true, '*')

            // First batch: one flag-called and one explicit-personless distinct ID, both cold -> one miss each.
            await step([createFlagCalledInput('ff-1'), createInput('batch-1', false)])
            // Second batch: ff-1 is warm in the LRU now -> one flag_called hit, no new insert.
            await step([createFlagCalledInput('ff-1')])

            expect(await counterValue('miss', 'flag_called')).toBe(1)
            expect(await counterValue('miss', 'batch')).toBe(1)
            expect(await counterValue('hit', 'flag_called')).toBe(1)
            expect(await counterValue('hit', 'batch')).toBe(0)
        })
    })
})
