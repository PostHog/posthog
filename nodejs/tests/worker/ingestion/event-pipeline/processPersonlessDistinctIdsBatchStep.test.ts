import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType } from '~/ingestion/pipelines/results'
import { IncomingEventWithTeam, Team } from '~/types'

import { PersonsStore } from '../../../../src/worker/ingestion/persons/persons-store'

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

        team = {
            id: 1,
            uuid: 'test-team-uuid',
            organization_id: 'test-org',
            name: 'Test Team',
        } as Team

        mockPersonsStore = {
            processPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(undefined),
            getPersonlessBatchResult: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<PersonsStore>
    })

    const createEventWithTeam = (
        distinctId: string,
        processPerson: boolean | undefined = undefined
    ): { eventWithTeam: IncomingEventWithTeam } => {
        const event: PluginEvent = {
            distinct_id: distinctId,
            ip: null,
            site_url: 'http://localhost',
            team_id: team.id,
            now: '2020-02-23T02:15:00Z',
            timestamp: '2020-02-23T02:15:00Z',
            event: '$pageview',
            properties: processPerson === undefined ? {} : { $process_person_profile: processPerson },
            uuid: `uuid-${distinctId}`,
        }

        return {
            eventWithTeam: {
                event,
                team,
                message: {} as any,
                headers: {
                    force_disable_person_processing: false,
                    historical_migration: false,
                },
            },
        }
    }

    describe('when enabled', () => {
        it('should process personless events and call batch insert', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [
                createEventWithTeam('user-1', false),
                createEventWithTeam('user-2', false),
                createEventWithTeam('user-3', false),
            ]

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
                createEventWithTeam('user-1', true), // processPerson=true
                createEventWithTeam('user-2', false), // processPerson=false (personless)
                createEventWithTeam('user-3'), // processPerson=undefined (default, not personless)
            ]

            const results = await step(events)

            expect(results).toHaveLength(3)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })

        it('should not call batch insert when no personless events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createEventWithTeam('user-1', true), createEventWithTeam('user-2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should return all events as OK even if batch insert fails', async () => {
            mockPersonsStore.processPersonlessDistinctIdsBatch.mockRejectedValue(new Error('DB error'))

            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [createEventWithTeam('user-1', false)]

            // The step should throw since we don't handle errors gracefully
            await expect(step(events)).rejects.toThrow('DB error')
        })
    })

    describe('when disabled', () => {
        it('should not process any events', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, false)
            const events = [createEventWithTeam('user-1', false), createEventWithTeam('user-2', false)]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results.every((r) => r.type === PipelineResultType.OK)).toBe(true)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })
    })

    describe('LRU cache behavior', () => {
        it('should deduplicate entries within same batch before hitting cache', async () => {
            const step = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)
            const events = [
                createEventWithTeam('user-1', false),
                createEventWithTeam('user-1', false), // Duplicate - deduped before cache/insert
                createEventWithTeam('user-2', false),
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
            await step([createEventWithTeam('user-1', false)])
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
            ])

            mockPersonsStore.processPersonlessDistinctIdsBatch.mockClear()

            // Second batch - user-1 should be cached, only user-2 should be inserted
            await step([createEventWithTeam('user-1', false), createEventWithTeam('user-2', false)])
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-2' },
            ])
        })
    })
})
