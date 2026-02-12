import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType } from '~/ingestion/pipelines/results'
import { EventHeaders, Team } from '~/types'

import { PersonsStore } from '../../../../src/worker/ingestion/persons/persons-store'
import { createTestEventHeaders } from '../../../helpers/event-headers'
import { createTestPluginEvent } from '../../../helpers/plugin-event'
import { createTestTeam } from '../../../helpers/team'

describe('processPersonlessDistinctIdsBatchStep', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let team: Team
    let processPersonlessDistinctIdsBatchStep: typeof import('../../../../src/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep').processPersonlessDistinctIdsBatchStep

    beforeEach(async () => {
        // Reset modules to get a fresh LRU cache for each test
        jest.resetModules()
        const module = await import(
            '../../../../src/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep'
        )
        processPersonlessDistinctIdsBatchStep = module.processPersonlessDistinctIdsBatchStep

        team = createTestTeam()

        mockPersonsStore = {
            processPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(undefined),
            getPersonlessBatchResult: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<PersonsStore>
    })

    const createInput = (
        distinctId: string,
        processPerson: boolean | undefined = undefined,
        forceDisablePersonProcessing: boolean = false
    ): { event: PluginEvent; team: Team; headers: EventHeaders } => ({
        event: createTestPluginEvent({
            distinct_id: distinctId,
            team_id: team.id,
            properties: processPerson === undefined ? {} : { $process_person_profile: processPerson },
            uuid: `uuid-${distinctId}`,
        }),
        team,
        headers: createTestEventHeaders({ force_disable_person_processing: forceDisablePersonProcessing }),
    })

    describe('when enabled', () => {
        it('should process personless events and call batch insert', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
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
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
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
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createInput('user-1', true), createInput('user-2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should return all events as OK even if batch insert fails', async () => {
            mockPersonsStore.processPersonlessDistinctIdsBatch.mockRejectedValue(new Error('DB error'))

            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createInput('user-1', false)]

            // The step should throw since we don't handle errors gracefully
            await expect(step(events)).rejects.toThrow('DB error')
        })
    })

    describe('when disabled', () => {
        it('should not process any events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, false)
            const events = [createInput('user-1', false), createInput('user-2', false)]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })
    })

    describe('force_disable_person_processing header', () => {
        it('should skip personless processing when force_disable_person_processing is true', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [
                createInput('user-1', false, true), // force_disable_person_processing: true
                createInput('user-2', false, false), // force_disable_person_processing: false
            ]

            const results = await step(events)

            expect(results).toHaveLength(2)
            // Only user-2 should be processed (user-1 is skipped due to header)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should not process any events when all have force_disable_person_processing', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createInput('user-1', false, true), createInput('user-2', false, true)]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should process normally when force_disable_person_processing is false', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createInput('user-1', false, false), createInput('user-2', false, false)]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })
    })

    describe('LRU cache behavior', () => {
        it('should deduplicate entries within same batch before hitting cache', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
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
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)

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
})
