import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiConfig } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { saveTagFilters } from '../components/resourceTagFilters'
import {
    llmAnalyticsScoreDefinitionsList as aiObservabilityScoreDefinitionsList,
    llmAnalyticsScoreDefinitionsPartialUpdate as aiObservabilityScoreDefinitionsPartialUpdate,
} from '../generated/api'
import type { ScoreDefinitionApi as ScoreDefinition } from '../generated/api.schemas'
import {
    aiObservabilityScoreDefinitionsLogic,
    SCORE_DEFINITIONS_PER_PAGE,
} from './aiObservabilityScoreDefinitionsLogic'

jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest.fn(),
    llmAnalyticsScoreDefinitionsPartialUpdate: jest.fn(),
}))

const mockAIObservabilityScoreDefinitionsList = aiObservabilityScoreDefinitionsList as jest.MockedFunction<
    typeof aiObservabilityScoreDefinitionsList
>
const mockAIObservabilityScoreDefinitionsPartialUpdate =
    aiObservabilityScoreDefinitionsPartialUpdate as jest.MockedFunction<
        typeof aiObservabilityScoreDefinitionsPartialUpdate
    >

const mockScoreDefinition: ScoreDefinition = {
    tags: [],
    id: 'score_def_1',
    short_name: '',
    name: 'Quality',
    description: 'Reusable quality scorer',
    kind: 'categorical',
    archived: false,
    current_version: 2,
    current_version_id: null,
    config: {
        options: [
            { key: 'good', label: 'Good' },
            { key: 'bad', label: 'Bad' },
        ],
    },
    created_by: {
        id: 1,
        uuid: 'test-uuid-1',
        distinct_id: 'test-distinct-id-1',
        first_name: 'Test',
        email: 'test@example.com',
        hedgehog_config: null,
    },
    created_at: '2026-03-11T00:00:00Z',
    updated_by: null,
    updated_at: '2026-03-11T00:00:00Z',
    team: MOCK_DEFAULT_TEAM.id,
}

describe('aiObservabilityScoreDefinitionsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        localStorage.clear()
        jest.resetAllMocks()
        mockAIObservabilityScoreDefinitionsList.mockResolvedValue({
            results: [mockScoreDefinition],
            count: 1,
            next: null,
            previous: null,
        })
        mockAIObservabilityScoreDefinitionsPartialUpdate.mockResolvedValue(mockScoreDefinition)
    })

    it.each([
        { orderBy: undefined, expectedOrder: '-updated_at' },
        { orderBy: 'invalid', expectedOrder: '-updated_at' },
        { orderBy: 'name', expectedOrder: 'name' },
    ])('loads scorers with sort $expectedOrder for URL sort $orderBy', async ({ orderBy, expectedOrder }) => {
        router.actions.push(urls.aiObservabilityScorers(), { order_by: orderBy })
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockAIObservabilityScoreDefinitionsList).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: undefined,
            kind: undefined,
            archived: false,
            order_by: expectedOrder,
            offset: 0,
            limit: SCORE_DEFINITIONS_PER_PAGE,
        })
        expect(logic.values.sorting).toEqual(
            expectedOrder === 'name' ? { columnKey: 'name', order: 1 } : { columnKey: 'updated_at', order: -1 }
        )
        await expectLogic(logic, () => logic.actions.setFilters({ search: 'quality' })).toFinishAllListeners()
        expect(router.values.searchParams.order_by).toBe(expectedOrder === '-updated_at' ? undefined : expectedOrder)
    })

    it.each(['saved', 'url'])('waits for the project before restoring %s tag filters', async (source) => {
        const selection = { tags: ['quality'], tag_match: 'all' as const }
        saveTagFilters('scorers', selection)
        router.actions.push(urls.aiObservabilityScorers(), source === 'url' ? { tags: ['shared'] } : {})
        teamLogic.actions.loadCurrentTeamSuccess(null)
        const currentTeamId = jest.spyOn(ApiConfig, 'getCurrentTeamId').mockImplementation(() => {
            throw new Error('Team ID is not known.')
        })
        const logic = aiObservabilityScoreDefinitionsLogic()
        try {
            expect(() => logic.mount()).not.toThrow()
            await expectLogic(logic).toFinishAllListeners()
            expect(mockAIObservabilityScoreDefinitionsList).not.toHaveBeenCalled()
        } finally {
            currentTeamId.mockRestore()
        }

        await expectLogic(logic, () =>
            teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
        ).toFinishAllListeners()
        expect(logic.values.filters.tags).toEqual(source === 'url' ? ['shared'] : ['quality'])
        expect(mockAIObservabilityScoreDefinitionsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ tags: JSON.stringify(source === 'url' ? ['shared'] : ['quality']), offset: 0 })
        )
    })

    it('updates filters and resets pagination', async () => {
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setFilters({ page: 3 }, false)
            logic.actions.setFilters({ search: 'quality', kind: 'categorical', archived: 'true', created_by: 42 })
        }).toFinishAllListeners()

        expect(logic.values.filters).toEqual({
            tags: [],
            tag_match: 'any',
            page: 1,
            search: 'quality',
            created_by: 42,
            kind: 'categorical',
            archived: 'true',
            order_by: '-updated_at',
        })
        expect(mockAIObservabilityScoreDefinitionsList).toHaveBeenLastCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            search: 'quality',
            created_by: 42,
            kind: 'categorical',
            archived: true,
            order_by: '-updated_at',
            offset: 0,
            limit: SCORE_DEFINITIONS_PER_PAGE,
        })
    })

    it('restores tag filters on return and lets shared URLs override them', async () => {
        router.actions.push(urls.aiObservabilityScorers())
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()
        await expectLogic(logic, () =>
            logic.actions.setFilters({ tags: ['quality', 'production'], tag_match: 'all' }, true, false)
        ).toFinishAllListeners()
        expect(router.values.searchParams).toMatchObject({ tags: ['quality', 'production'], tag_match: 'all' })
        expect(mockAIObservabilityScoreDefinitionsList).toHaveBeenLastCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            expect.objectContaining({ tags: '["quality","production"]', tag_match: 'all' })
        )
        router.actions.push(urls.aiObservabilityDatasets())
        router.actions.push(urls.aiObservabilityScorers())
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.tags).toEqual(['quality', 'production'])
        expect(router.values.searchParams.tags).toEqual(['quality', 'production'])
        router.actions.push(urls.aiObservabilityScorers(), { tags: ['other'], tag_match: 'any' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters.tags).toEqual(['other'])
    })

    it.each([
        [{}, true],
        [{ search: 'missing' }, false],
        [{ kind: 'boolean' }, false],
        [{ created_by: 1 }, false],
        [{ tags: ['quality'] }, false],
        [{ archived: 'true' }, false],
        [{ page: 2 }, false],
    ])('only shows setup after an unfiltered empty response for %p', async (filters, showsSetup) => {
        const requests: ((value: Awaited<ReturnType<typeof aiObservabilityScoreDefinitionsList>>) => void)[] = []
        mockAIObservabilityScoreDefinitionsList.mockImplementation(
            () =>
                new Promise((resolve) => {
                    requests.push(resolve)
                })
        )

        router.actions.push(urls.aiObservabilityScorers(), filters)
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()

        expect(logic.values.scoreDefinitionsLoading).toBe(true)
        expect(logic.values.scoreDefinitionCountLabel).toBe('')
        expect(logic.values.showEmptyState).toBe(false)

        for (const resolveRequest of requests) {
            resolveRequest({ results: [], count: 0, next: null, previous: null })
        }

        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.scoreDefinitionCountLabel).toBe('0 scorers')
        expect(logic.values.showEmptyState).toBe(showsSetup)

        if (showsSetup) {
            mockAIObservabilityScoreDefinitionsList.mockRejectedValueOnce(new Error('Unavailable'))
            await expectLogic(logic, () => logic.actions.loadScoreDefinitions(false)).toFinishAllListeners()
            expect(logic.values.showEmptyState).toBe(false)
        }
    })

    it('archives through logic and reloads the list', async () => {
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.toggleArchive(mockScoreDefinition)
        }).toFinishAllListeners()

        expect(mockAIObservabilityScoreDefinitionsPartialUpdate).toHaveBeenCalledWith(
            String(MOCK_DEFAULT_TEAM.id),
            'score_def_1',
            {
                archived: true,
            }
        )
        expect(mockAIObservabilityScoreDefinitionsList).toHaveBeenCalledTimes(2)
        expect(logic.values.isArchivingDefinition(mockScoreDefinition.id)).toBe(false)
    })
    it('restores scorer filters and keeps filter changes on the canonical management route', async () => {
        router.actions.push(urls.aiObservabilityScorers(), { search: 'quality', archived: 'all' })
        const logic = aiObservabilityScoreDefinitionsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.filters).toMatchObject({ search: 'quality', archived: '' })

        await expectLogic(logic, () =>
            logic.actions.setFilters({ kind: 'boolean' }, true, false)
        ).toFinishAllListeners()
        expect(router.values.location.pathname).toContain(urls.aiObservabilityScorers())
        expect(router.values.searchParams).toMatchObject({ search: 'quality', archived: 'all', kind: 'boolean' })
        expect(router.values.searchParams.human_reviews_tab).toBeUndefined()
    })
})
