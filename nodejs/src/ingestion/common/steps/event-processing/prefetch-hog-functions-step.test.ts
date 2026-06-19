import { v4 } from 'uuid'

import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PipelineResultType } from '~/ingestion/framework/results'
import { ProjectId, Team } from '~/types'

import { PrefetchHogFunctionsStepInput, createPrefetchHogFunctionsStep } from './prefetch-hog-functions-step'

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    secret_api_token: null,
    session_recording_opt_in: true,
    person_processing_opt_out: null,
    heatmaps_opt_in: null,
    ingested_event: true,
    person_display_name_properties: null,
    test_account_filters: null,
    cookieless_server_hash_mode: null,
    timezone: 'UTC',
    available_features: [],
    drop_events_older_than_seconds: null,
    extra_settings: null,
    ...overrides,
})

const createTestInput = (team: Team): PrefetchHogFunctionsStepInput => ({
    team,
})

describe('prefetchHogFunctionsStep', () => {
    // The step only depends on the HogTransformer contract; it delegates the actual clear/fetch/cache
    // work to prefetchTransformationStatesForTeams (covered by the hog-transformer service tests).
    let prefetchTransformationStatesForTeams: jest.Mock
    let mockHogTransformer: HogTransformer

    beforeEach(() => {
        prefetchTransformationStatesForTeams = jest.fn().mockResolvedValue(undefined)
        mockHogTransformer = { prefetchTransformationStatesForTeams } as unknown as HogTransformer
    })

    it('refreshes transformation states for the batch team IDs', async () => {
        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)

        await step([createTestInput(createTestTeam({ id: 1 }))])

        expect(prefetchTransformationStatesForTeams).toHaveBeenCalledWith([1])
    })

    it('returns an empty array and still refreshes with no team IDs when no events provided', async () => {
        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)

        const results = await step([])

        expect(results).toEqual([])
        expect(prefetchTransformationStatesForTeams).toHaveBeenCalledWith([])
    })

    it('deduplicates team IDs across the batch', async () => {
        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const team1 = createTestTeam({ id: 1 })
        const team2 = createTestTeam({ id: 2 })
        const team3 = createTestTeam({ id: 3 })

        await step([
            createTestInput(team1),
            createTestInput(team1),
            createTestInput(team2),
            createTestInput(team3),
            createTestInput(team2),
        ])

        expect(prefetchTransformationStatesForTeams).toHaveBeenCalledTimes(1)
        expect(prefetchTransformationStatesForTeams).toHaveBeenCalledWith([1, 2, 3])
    })

    it('returns all events as OK results unchanged', async () => {
        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const team = createTestTeam({ id: 1 })
        const inputs = [
            { team, extraField: 'value1' },
            { team, extraField: 'value2' },
        ]

        const results = await step(inputs)

        expect(results).toHaveLength(2)
        expect(results[0].type).toBe(PipelineResultType.OK)
        expect(results[1].type).toBe(PipelineResultType.OK)
        if (results[0].type === PipelineResultType.OK && results[1].type === PipelineResultType.OK) {
            expect(results[0].value).toEqual(inputs[0])
            expect(results[1].value).toEqual(inputs[1])
        }
    })

    describe('sampling rate', () => {
        let mockRandom: jest.SpyInstance

        beforeEach(() => {
            mockRandom = jest.spyOn(Math, 'random')
        })

        afterEach(() => {
            mockRandom.mockRestore()
        })

        it('prefetches when random value is below sample rate', async () => {
            mockRandom.mockReturnValue(0.2)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)

            await step([createTestInput(createTestTeam({ id: 1 }))])

            expect(prefetchTransformationStatesForTeams).toHaveBeenCalledWith([1])
        })

        it('skips prefetching when random value is above sample rate', async () => {
            mockRandom.mockReturnValue(0.4)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)

            const results = await step([createTestInput(createTestTeam({ id: 1 }))])

            expect(prefetchTransformationStatesForTeams).not.toHaveBeenCalled()
            expect(results).toHaveLength(1)
        })

        it('skips prefetching when random value equals sample rate', async () => {
            mockRandom.mockReturnValue(0.3)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)

            await step([createTestInput(createTestTeam({ id: 1 }))])

            // 0.3 < 0.3 is false, so should skip
            expect(prefetchTransformationStatesForTeams).not.toHaveBeenCalled()
        })

        it('always prefetches when sample rate is 1', async () => {
            mockRandom.mockReturnValue(0.999)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)

            await step([createTestInput(createTestTeam({ id: 1 }))])

            expect(prefetchTransformationStatesForTeams).toHaveBeenCalledWith([1])
        })

        it('skips prefetching when sample rate is 0', async () => {
            mockRandom.mockReturnValue(0.5)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0)

            await step([createTestInput(createTestTeam({ id: 1 }))])

            expect(prefetchTransformationStatesForTeams).not.toHaveBeenCalled()
        })
    })
})
