/**
 * Integration tests for person processing with force_disable_person_processing header.
 *
 * These tests verify that when force_disable_person_processing is set:
 * 1. Person prefetching is skipped (no database queries)
 * 2. Personless distinct ID entries are NOT created (even if person exists)
 * 3. Events still flow through the pipeline correctly
 */
import { ok } from '~/ingestion/pipelines/results'
import { Team } from '~/types'
import { prefetchPersonsStep } from '~/worker/ingestion/event-pipeline/prefetchPersonsStep'
import { processPersonlessDistinctIdsBatchStep } from '~/worker/ingestion/event-pipeline/processPersonlessDistinctIdsBatchStep'
import { PersonsStore } from '~/worker/ingestion/persons/persons-store'

import { createTestEventHeaders } from '../../../helpers/event-headers'
import { createTestPipelineEvent } from '../../../helpers/pipeline-event'
import { createTestPluginEvent } from '../../../helpers/plugin-event'
import { createTestTeam } from '../../../helpers/team'

describe('Person processing integration with force_disable_person_processing', () => {
    let mockPersonsStore: jest.Mocked<PersonsStore>
    let team: Team

    beforeEach(() => {
        team = createTestTeam()
        mockPersonsStore = {
            prefetchPersons: jest.fn().mockResolvedValue(undefined),
            processPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(undefined),
            getPersonlessBatchResult: jest.fn().mockReturnValue(undefined),
        } as unknown as jest.Mocked<PersonsStore>
    })

    describe('when force_disable_person_processing is true', () => {
        it('should skip prefetch but allow event through pipeline', async () => {
            const prefetchStep = prefetchPersonsStep(mockPersonsStore, true)
            const event = createTestPipelineEvent({ distinct_id: 'user-123' })
            const headers = createTestEventHeaders({ force_disable_person_processing: true })

            const input = [{ event, team, headers }]
            const result = await prefetchStep(input)

            // Event should pass through
            expect(result).toEqual([ok(input[0])])
            // But no prefetch should happen
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()
        })

        it('should NOT create personless entry when force_disable_person_processing is true', async () => {
            // This is the key test: when force_disable_person_processing is set,
            // we skip ALL person processing, including personless distinct ID creation.
            // This is correct because the header indicates the event is from overflow
            // or rate-limited, and we don't want to do ANY person-related DB operations.

            const personlessStep = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)

            const event = createTestPluginEvent({
                distinct_id: 'user-456',
                team_id: team.id,
                properties: { $process_person_profile: false },
            })
            const headers = createTestEventHeaders({ force_disable_person_processing: true })

            const input = [{ event, team, headers }]
            const result = await personlessStep(input)

            // Event should pass through
            expect(result).toHaveLength(1)
            // Personless entry should NOT be created due to force_disable_person_processing header
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })
    })

    describe('end-to-end pipeline flow', () => {
        it('should skip both prefetch and personless when force_disable_person_processing is true', async () => {
            // Simulate the full pipeline flow for an event with:
            // - force_disable_person_processing: true (from header)
            // - $process_person_profile: false (from event property)

            const prefetchStep = prefetchPersonsStep(mockPersonsStore, true)
            const personlessStep = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)

            const pipelineEvent = createTestPipelineEvent({
                distinct_id: 'user-789',
                properties: { $process_person_profile: false },
            })
            const headers = createTestEventHeaders({ force_disable_person_processing: true })

            // Step 1: Prefetch (with headers) - should be skipped
            const prefetchInput = [{ event: pipelineEvent, team, headers }]
            const prefetchResult = await prefetchStep(prefetchInput)

            expect(prefetchResult).toEqual([ok(prefetchInput[0])])
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()

            // Step 2: Personless processing (with headers) - should also be skipped
            const pluginEvent = createTestPluginEvent({
                distinct_id: 'user-789',
                team_id: team.id,
                properties: { $process_person_profile: false },
            })
            const personlessInput = [{ event: pluginEvent, team, headers }]
            const personlessResult = await personlessStep(personlessInput)

            expect(personlessResult).toHaveLength(1)
            // Personless should be skipped due to force_disable_person_processing header
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should prefetch AND skip personless when force_disable_person_processing is false', async () => {
            // Normal flow: prefetch happens, personless only if $process_person_profile is false

            const prefetchStep = prefetchPersonsStep(mockPersonsStore, true)
            const personlessStep = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)

            const pipelineEvent = createTestPipelineEvent({
                distinct_id: 'user-999',
                properties: { $process_person_profile: true },
            })
            const headers = createTestEventHeaders({ force_disable_person_processing: false })

            // Step 1: Prefetch should happen
            const prefetchInput = [{ event: pipelineEvent, team, headers }]
            await prefetchStep(prefetchInput)

            expect(mockPersonsStore.prefetchPersons).toHaveBeenCalledWith([{ teamId: team.id, distinctId: 'user-999' }])

            // Step 2: Personless should be skipped because $process_person_profile is true
            const pluginEvent = createTestPluginEvent({
                distinct_id: 'user-999',
                team_id: team.id,
                properties: { $process_person_profile: true },
            })
            const personlessInput = [{ event: pluginEvent, team, headers }]
            await personlessStep(personlessInput)

            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })

        it('should handle mixed batch with some events having force_disable_person_processing', async () => {
            const prefetchStep = prefetchPersonsStep(mockPersonsStore, true)

            const event1 = createTestPipelineEvent({ distinct_id: 'user-1' })
            const headers1 = createTestEventHeaders({ force_disable_person_processing: false })

            const event2 = createTestPipelineEvent({ distinct_id: 'user-2' })
            const headers2 = createTestEventHeaders({ force_disable_person_processing: true })

            const event3 = createTestPipelineEvent({ distinct_id: 'user-3' })
            const headers3 = createTestEventHeaders({ force_disable_person_processing: false })

            const input = [
                { event: event1, team, headers: headers1 },
                { event: event2, team, headers: headers2 },
                { event: event3, team, headers: headers3 },
            ]

            const result = await prefetchStep(input)

            // All events should pass through
            expect(result).toHaveLength(3)

            // Only user-1 and user-3 should be prefetched (user-2 has force_disable_person_processing)
            expect(mockPersonsStore.prefetchPersons).toHaveBeenCalledWith([
                { teamId: team.id, distinctId: 'user-1' },
                { teamId: team.id, distinctId: 'user-3' },
            ])
        })
    })

    describe('scenario: existing person with force_disable_person_processing', () => {
        it('should skip prefetch and not create personless entry when person exists but processing is disabled', async () => {
            // This is the critical test case from the user's request:
            // - A person already exists in the database
            // - Event comes with force_disable_person_processing: true
            // - We should: Skip prefetch, NOT create personless entry

            const prefetchStep = prefetchPersonsStep(mockPersonsStore, true)
            const personlessStep = processPersonlessDistinctIdsBatchStep(mockPersonsStore, true)

            const pipelineEvent = createTestPipelineEvent({
                distinct_id: 'existing-user',
                properties: { $process_person_profile: false },
            })
            const headers = createTestEventHeaders({
                force_disable_person_processing: true,
                distinct_id: 'existing-user',
            })

            // Step 1: Prefetch should be skipped
            const prefetchInput = [{ event: pipelineEvent, team, headers }]
            const prefetchResult = await prefetchStep(prefetchInput)

            expect(prefetchResult).toEqual([ok(prefetchInput[0])])
            expect(mockPersonsStore.prefetchPersons).not.toHaveBeenCalled()

            // Step 2: Personless entry should NOT be created
            const pluginEvent = createTestPluginEvent({
                distinct_id: 'existing-user',
                team_id: team.id,
                properties: { $process_person_profile: false },
            })
            const personlessInput = [{ event: pluginEvent, team, headers }]
            const personlessResult = await personlessStep(personlessInput)

            expect(personlessResult).toHaveLength(1)
            expect(mockPersonsStore.processPersonlessDistinctIdsBatch).not.toHaveBeenCalled()
        })
    })
})
