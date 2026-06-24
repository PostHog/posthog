import { DateTime } from 'luxon'

import { PersonsStoreForBatch } from '~/ingestion/common/persons/persons-store-for-batch'
import { isOkResult } from '~/ingestion/framework/results'
import { PluginEvent } from '~/plugin-scaffold'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'
import { Team } from '~/types'

// The batch step (processPersonlessDistinctIdsBatchStep) and the per-event step
// (processPersonlessStep) are coupled through the module-level LRU in
// personless-distinct-id-cache: the batch step pre-inserts the posthog_personlessdistinctid
// row and marks the LRU, so the per-event step finds a hit and skips its own single-row
// insert. Both steps are dynamically imported after resetModules so they share one fresh LRU.
describe('flag-called personless batching: batch step → per-event step', () => {
    let mockPersonsStore: jest.Mocked<PersonsStoreForBatch>
    let team: Team
    let processPersonlessDistinctIdsBatchStep: typeof import('~/ingestion/pipelines/analytics/steps/processPersonlessDistinctIdsBatchStep').processPersonlessDistinctIdsBatchStep
    let createProcessPersonlessStep: typeof import('~/ingestion/common/steps/event-processing/process-personless-step').createProcessPersonlessStep

    beforeEach(async () => {
        jest.resetModules()
        processPersonlessDistinctIdsBatchStep = (
            await import('~/ingestion/pipelines/analytics/steps/processPersonlessDistinctIdsBatchStep.js')
        ).processPersonlessDistinctIdsBatchStep
        createProcessPersonlessStep = (
            await import('~/ingestion/common/steps/event-processing/process-personless-step.js')
        ).createProcessPersonlessStep

        team = createTestTeam()

        mockPersonsStore = {
            // No real person exists for the distinct ID under test.
            fetchForChecking: jest.fn().mockResolvedValue(null),
            fetchForUpdate: jest.fn().mockResolvedValue(null),
            getPersonlessBatchResult: jest.fn().mockReturnValue(undefined),
            addPersonlessDistinctId: jest.fn().mockResolvedValue(false),
            processPersonlessDistinctIdsBatch: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<PersonsStoreForBatch>
    })

    const flagCalledEvent = (distinctId: string): PluginEvent =>
        createTestPluginEvent({
            distinct_id: distinctId,
            team_id: team.id,
            event: '$feature_flag_called',
            properties: {},
            uuid: `uuid-${distinctId}`,
        })

    const perEventInput = (event: PluginEvent) => ({
        normalizedEvent: event,
        team,
        timestamp: DateTime.utc(),
        processPerson: true,
        processPersonExplicitlyTrue: false,
        forceDisablePersonProcessing: false,
        personsStoreForBatch: mockPersonsStore,
    })

    it('per-event step skips its single-row insert because the batch step already inserted the row', async () => {
        const event = flagCalledEvent('user-1')

        // Batch step inserts the personless distinct ID and marks the shared LRU.
        await processPersonlessDistinctIdsBatchStep(
            true,
            '*'
        )([{ event, team, personsStoreForBatch: mockPersonsStore }])
        expect(mockPersonsStore.processPersonlessDistinctIdsBatch).toHaveBeenCalledWith([
            { teamId: team.id, distinctId: 'user-1' },
        ])

        // Per-event step now sees the LRU hit and must NOT do its own single-row insert.
        const result = await createProcessPersonlessStep('*')(perEventInput(event))

        expect(mockPersonsStore.addPersonlessDistinctId).not.toHaveBeenCalled()
        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            // Still defaulted to personless.
            expect(result.value.processPerson).toBe(false)
        }
    })

    it('per-event step falls back to its single-row insert when the batch step did not run', async () => {
        const event = flagCalledEvent('user-1')

        // No batch step this time, so the LRU is cold.
        const result = await createProcessPersonlessStep('*')(perEventInput(event))

        expect(mockPersonsStore.addPersonlessDistinctId).toHaveBeenCalledTimes(1)
        expect(mockPersonsStore.addPersonlessDistinctId).toHaveBeenCalledWith(team.id, 'user-1')
        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value.processPerson).toBe(false)
        }
    })
})
