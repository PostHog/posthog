import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TaggerApi } from '../generated/api.schemas'
import { llmTaggersLogic } from './llmTaggersLogic'

const makeTagger = (overrides: Partial<TaggerApi> & { id: string; name: string }): TaggerApi => ({
    description: '',
    enabled: false,
    tagger_type: 'llm',
    tagger_config: {
        prompt: 'Test prompt',
        tags: [{ name: 'test-tag', description: 'A test tag' }],
        min_tags: 0,
        max_tags: null,
    },
    conditions: [{ id: 'cond-1', rollout_percentage: 100, properties: [] }],
    model_configuration: null,
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: { id: 1, uuid: 'user-1', email: 'test@example.com', hedgehog_config: null },
    deleted: false,
    migrated_to_evaluation_id: null,
    ...overrides,
})

const mockTaggers: TaggerApi[] = [
    makeTagger({ id: 'tagger-1', name: 'Topic tags', description: 'Tag topics' }),
    makeTagger({
        id: 'tagger-2',
        name: 'Safety flags',
        description: 'Flag safety issues',
        tagger_config: {
            prompt: 'Check safety',
            tags: [
                { name: 'pii', description: 'PII detected' },
                { name: 'harmful', description: 'Harmful content' },
            ],
            min_tags: 0,
            max_tags: null,
        },
    }),
    makeTagger({
        id: 'tagger-3',
        name: 'Hog classifier',
        tagger_type: 'hog',
        tagger_config: {
            source: 'return []',
            tags: [{ name: 'billing', description: 'Billing related' }],
        },
    }),
]

describe('llmTaggersLogic', () => {
    let logic: ReturnType<typeof llmTaggersLogic.build>

    describe('loading existing taggers', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/taggers/': { results: mockTaggers },
                },
            })
            initKeaTests()
            logic = llmTaggersLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('loads taggers on mount', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggers', 'loadTaggersSuccess']).toMatchValues({
                taggers: mockTaggers,
                taggersLoading: false,
            })
        })

        it('sets taggersLoading while loading', async () => {
            await expectLogic(logic).toMatchValues({
                taggersLoading: true,
            })

            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess']).toMatchValues({
                taggersLoading: false,
            })
        })
    })

    describe('filteredTaggers selector', () => {
        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/taggers/': { results: mockTaggers },
                },
            })
            initKeaTests()
            logic = llmTaggersLogic()
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('returns all taggers when filter is empty', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            expect(logic.values.filteredTaggers).toHaveLength(3)
        })

        it('filters by tagger name', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            logic.actions.setTaggersFilter('topic')

            await expectLogic(logic).toMatchValues({
                filteredTaggers: [expect.objectContaining({ id: 'tagger-1', name: 'Topic tags' })],
            })
        })

        it('filters by tagger description', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            logic.actions.setTaggersFilter('safety issues')

            await expectLogic(logic).toMatchValues({
                filteredTaggers: [expect.objectContaining({ id: 'tagger-2' })],
            })
        })

        it('filters by tag name', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            logic.actions.setTaggersFilter('billing')

            await expectLogic(logic).toMatchValues({
                filteredTaggers: [expect.objectContaining({ id: 'tagger-3' })],
            })
        })

        it('filter is case-insensitive', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            logic.actions.setTaggersFilter('TOPIC')

            await expectLogic(logic).toMatchValues({
                filteredTaggers: [expect.objectContaining({ id: 'tagger-1' })],
            })
        })

        it('returns empty when no match', async () => {
            await expectLogic(logic).toDispatchActions(['loadTaggersSuccess'])

            logic.actions.setTaggersFilter('nonexistent')

            await expectLogic(logic).toMatchValues({
                filteredTaggers: [],
            })
        })
    })
})
