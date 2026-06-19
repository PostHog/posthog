import { PipelineEvent, Team } from '~/types'

import { PipelineResultType, isOkResult } from '../../../ingestion/pipelines/results'
import { PersonsStoreForBatch } from '../persons/persons-store-for-batch'
import { prefetchPersonsStep } from './prefetchPersonsStep'

type TestInput = { event: PipelineEvent; team: Team; personsStoreForBatch: PersonsStoreForBatch }

function createStore(batchId: number): PersonsStoreForBatch {
    return {
        batchId,
        prefetchPersons: jest.fn().mockResolvedValue(undefined),
    } as unknown as PersonsStoreForBatch
}

function createInput(distinctId: string, teamId: number, personsStoreForBatch: PersonsStoreForBatch): TestInput {
    return {
        event: { distinct_id: distinctId } as unknown as PipelineEvent,
        team: { id: teamId } as unknown as Team,
        personsStoreForBatch,
    }
}

describe('prefetchPersonsStep', () => {
    it('groups prefetch entries by batch store', async () => {
        const storeA = createStore(1)
        const storeB = createStore(2)
        const step = prefetchPersonsStep<TestInput>(true)

        const results = await step([
            createInput('user-a', 3, storeA),
            createInput('user-b', 4, storeB),
            createInput('user-c', 5, storeA),
        ])

        expect(results.map((result) => result.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.OK,
            PipelineResultType.OK,
        ])
        expect(results.filter(isOkResult).map((result) => result.value.event.distinct_id)).toEqual([
            'user-a',
            'user-b',
            'user-c',
        ])
        expect(storeA.prefetchPersons).toHaveBeenCalledWith([
            { teamId: 3, distinctId: 'user-a', batchId: 1 },
            { teamId: 5, distinctId: 'user-c', batchId: 1 },
        ])
        expect(storeB.prefetchPersons).toHaveBeenCalledWith([{ teamId: 4, distinctId: 'user-b', batchId: 2 }])
    })
})
