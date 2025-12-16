import { v4 } from 'uuid'

import { HogTransformerService } from '../../cdp/hog-transformations/hog-transformer.service'
import { ProjectId, Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { PrefetchHogFunctionsStepInput, createPrefetchHogFunctionsStep } from './prefetch-hog-functions-step'

const createTestTeam = (overrides: Partial<Team> = {}): Team => ({
    id: 1,
    project_id: 1 as ProjectId,
    organization_id: 'test-org-id',
    uuid: v4(),
    name: 'Test Team',
    anonymize_ips: false,
    api_token: 'test-api-token',
    slack_incoming_webhook: null,
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
    ...overrides,
})

const createTestInput = (team: Team): PrefetchHogFunctionsStepInput => ({
    team,
})

describe('prefetchHogFunctionsStep', () => {
    let mockHogTransformer: jest.Mocked<HogTransformerService>
    let mockGetHogFunctionIdsForTeams: jest.Mock

    beforeEach(() => {
        mockGetHogFunctionIdsForTeams = jest.fn()
        mockHogTransformer = {
            clearHogFunctionStates: jest.fn(),
            fetchAndCacheHogFunctionStates: jest.fn(),
            hogFunctionManager: {
                getHogFunctionIdsForTeams: mockGetHogFunctionIdsForTeams,
            },
        } as unknown as jest.Mocked<HogTransformerService>
    })

    it('clears cached hog function states before processing', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({})

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const input = createTestInput(createTestTeam())

        await step([input])

        expect(mockHogTransformer.clearHogFunctionStates).toHaveBeenCalledTimes(1)
    })

    it('returns events unchanged when no events provided', async () => {
        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)

        const results = await step([])

        expect(results).toEqual([])
        expect(mockHogTransformer.clearHogFunctionStates).toHaveBeenCalledTimes(1)
        expect(mockGetHogFunctionIdsForTeams).not.toHaveBeenCalled()
    })

    it('extracts unique team IDs and fetches hog function IDs', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({ 1: ['func-1', 'func-2'] })
        mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const team = createTestTeam({ id: 1 })
        const inputs = [createTestInput(team), createTestInput(team), createTestInput(team)]

        await step(inputs)

        expect(mockGetHogFunctionIdsForTeams).toHaveBeenCalledWith([1], ['transformation'])
    })

    it('handles multiple teams and deduplicates team IDs', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({
            1: ['func-1'],
            2: ['func-2'],
            3: ['func-3'],
        })
        mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const team1 = createTestTeam({ id: 1 })
        const team2 = createTestTeam({ id: 2 })
        const team3 = createTestTeam({ id: 3 })
        const inputs = [
            createTestInput(team1),
            createTestInput(team1),
            createTestInput(team2),
            createTestInput(team3),
            createTestInput(team2),
        ]

        await step(inputs)

        expect(mockGetHogFunctionIdsForTeams).toHaveBeenCalledTimes(1)
        const calledTeamIds = mockGetHogFunctionIdsForTeams.mock.calls[0][0]
        expect(calledTeamIds).toHaveLength(3)
        expect(calledTeamIds).toContain(1)
        expect(calledTeamIds).toContain(2)
        expect(calledTeamIds).toContain(3)
    })

    it('fetches and caches hog function states when functions exist', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({
            1: ['func-1', 'func-2'],
            2: ['func-3'],
        })
        mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const inputs = [createTestInput(createTestTeam({ id: 1 })), createTestInput(createTestTeam({ id: 2 }))]

        await step(inputs)

        expect(mockHogTransformer.fetchAndCacheHogFunctionStates).toHaveBeenCalledWith(['func-1', 'func-2', 'func-3'])
    })

    it('does not fetch hog function states when no functions exist', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({})

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const inputs = [createTestInput(createTestTeam({ id: 1 }))]

        await step(inputs)

        expect(mockHogTransformer.fetchAndCacheHogFunctionStates).not.toHaveBeenCalled()
    })

    it('returns all events as OK results unchanged', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({ 1: ['func-1'] })
        mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

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

    it('handles teams with empty hog function arrays', async () => {
        mockGetHogFunctionIdsForTeams.mockResolvedValue({
            1: [],
            2: [],
        })

        const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
        const inputs = [createTestInput(createTestTeam({ id: 1 })), createTestInput(createTestTeam({ id: 2 }))]

        await step(inputs)

        expect(mockHogTransformer.fetchAndCacheHogFunctionStates).not.toHaveBeenCalled()
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
            mockGetHogFunctionIdsForTeams.mockResolvedValue({ 1: ['func-1'] })
            mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)
            const inputs = [createTestInput(createTestTeam({ id: 1 }))]

            await step(inputs)

            expect(mockHogTransformer.clearHogFunctionStates).toHaveBeenCalled()
            expect(mockGetHogFunctionIdsForTeams).toHaveBeenCalled()
            expect(mockHogTransformer.fetchAndCacheHogFunctionStates).toHaveBeenCalledWith(['func-1'])
        })

        it('skips prefetching when random value is above sample rate', async () => {
            mockRandom.mockReturnValue(0.4)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)
            const inputs = [createTestInput(createTestTeam({ id: 1 }))]

            await step(inputs)

            expect(mockHogTransformer.clearHogFunctionStates).not.toHaveBeenCalled()
            expect(mockGetHogFunctionIdsForTeams).not.toHaveBeenCalled()
            expect(mockHogTransformer.fetchAndCacheHogFunctionStates).not.toHaveBeenCalled()
        })

        it('skips prefetching when random value equals sample rate', async () => {
            mockRandom.mockReturnValue(0.3)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0.3)
            const inputs = [createTestInput(createTestTeam({ id: 1 }))]

            await step(inputs)

            // 0.3 < 0.3 is false, so should skip
            expect(mockHogTransformer.clearHogFunctionStates).not.toHaveBeenCalled()
            expect(mockGetHogFunctionIdsForTeams).not.toHaveBeenCalled()
        })

        it('always prefetches when sample rate is 1', async () => {
            mockRandom.mockReturnValue(0.999)
            mockGetHogFunctionIdsForTeams.mockResolvedValue({ 1: ['func-1'] })
            mockHogTransformer.fetchAndCacheHogFunctionStates.mockResolvedValue(undefined)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 1)
            const inputs = [createTestInput(createTestTeam({ id: 1 }))]

            await step(inputs)

            expect(mockHogTransformer.clearHogFunctionStates).toHaveBeenCalled()
            expect(mockGetHogFunctionIdsForTeams).toHaveBeenCalled()
        })

        it('skips prefetching when sample rate is 0', async () => {
            mockRandom.mockReturnValue(0.5)

            const step = createPrefetchHogFunctionsStep(mockHogTransformer, 0)
            const inputs = [createTestInput(createTestTeam({ id: 1 }))]

            await step(inputs)

            expect(mockHogTransformer.clearHogFunctionStates).not.toHaveBeenCalled()
            expect(mockGetHogFunctionIdsForTeams).not.toHaveBeenCalled()
        })
    })
})
