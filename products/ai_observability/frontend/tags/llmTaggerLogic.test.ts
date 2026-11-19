import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TaggerApi } from '../generated/api.schemas'
import { llmTaggerLogic } from './llmTaggerLogic'

const mockTagger: TaggerApi = {
    id: 'tagger-123',
    name: 'Test Tagger',
    description: 'A test tagger',
    enabled: false,
    tagger_type: 'llm',
    tagger_config: {
        prompt: 'Tag this generation',
        tags: [
            { name: 'billing', description: 'Billing related' },
            { name: 'support', description: 'Support related' },
        ],
        min_tags: 0,
        max_tags: null,
    },
    conditions: [{ id: 'cond-1', rollout_percentage: 50, properties: [] }],
    model_configuration: {
        provider: 'openai',
        model: 'gpt-5-mini',
        provider_key_id: 'key-1',
        provider_key_name: 'OpenAI Key',
    },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    created_by: { id: 1, uuid: 'user-1', email: 'test@example.com', hedgehog_config: null },
    deleted: false,
    migrated_to_evaluation_id: null,
}

describe('llmTaggerLogic', () => {
    let logic: ReturnType<typeof llmTaggerLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/taggers/tagger-123/': mockTagger,
                '/api/projects/:team_id/taggers/missing/': () => [404, { detail: 'Not found.' }],
            },
            post: {
                '/api/environments/:team_id/query/:kind': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['an existing tagger', 'tagger-123', mockTagger],
        ['a missing tagger', 'missing', null],
    ])('loads %s and stops loading', async (_label, id, expectedTagger) => {
        logic = llmTaggerLogic({ id })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadTaggerSuccess'])
            .toMatchValues({ tagger: expectedTagger, taggerLoading: false })
    })

    it('loads tag runs on mount', async () => {
        logic = llmTaggerLogic({ id: 'tagger-123' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTagRuns'])
    })

    describe('loadTagRuns', () => {
        it('parses query results into TagRun objects', async () => {
            logic = llmTaggerLogic({ id: 'tagger-123' })
            logic.mount()

            // Wait for initial load (returns empty from default mock)
            await expectLogic(logic).toDispatchActions(['loadTagRunsSuccess'])

            // Now override the query mock and reload
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind': {
                        results: [
                            [
                                '2024-01-01T12:00:00Z',
                                '["billing","support"]',
                                'Found billing keyword',
                                'trace-1',
                                'event-1',
                                'tagger-123',
                                'Test Tagger',
                            ],
                        ],
                    },
                },
            })

            logic.actions.loadTagRuns()

            await expectLogic(logic)
                .toDispatchActions(['loadTagRunsSuccess'])
                .toMatchValues({
                    tagRuns: [
                        {
                            timestamp: '2024-01-01T12:00:00Z',
                            tags: ['billing', 'support'],
                            reasoning: 'Found billing keyword',
                            trace_id: 'trace-1',
                            target_event_id: 'event-1',
                            tagger_id: 'tagger-123',
                            tagger_name: 'Test Tagger',
                        },
                    ],
                })
        })

        // Regression: combining `values: { tagger_id }` with `{filters}` made the
        // backend's parse_select throw, the loader's catch silently returned [],
        // and the runs tab rendered empty even when matching events existed.
        // Lock in that the request inlines (and escapes) the id into the query
        // string and does not send a `values` dict.
        it.each([
            ['plain id', 'tagger-abc', "properties.$ai_tagger_id = 'tagger-abc'"],
            ['id with single quote', "o'malley", "properties.$ai_tagger_id = 'o\\'malley'"],
            ['id with backslash', 'tagger\\abc', "properties.$ai_tagger_id = 'tagger\\\\abc'"],
        ])('inlines the tagger id without a values dict (%s)', async (_label, taggerId, expectedSnippet) => {
            const capturedQueries: { query: string; values?: unknown }[] = []
            useMocks({
                get: {
                    [`/api/projects/:team_id/taggers/${taggerId}/`]: mockTagger,
                },
                post: {
                    '/api/environments/:team_id/query/:kind': async ({ request }) => {
                        const body = (await request.json()) as { query?: { query?: string; values?: unknown } }
                        if (body.query?.query?.includes('$ai_tagger_id')) {
                            capturedQueries.push({
                                query: body.query.query,
                                values: body.query.values,
                            })
                        }
                        return [200, { results: [] }]
                    },
                },
            })

            logic = llmTaggerLogic({ id: taggerId })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadTagRunsSuccess'])

            expect(capturedQueries).toHaveLength(1)
            const sent = capturedQueries[0]
            expect(sent.query).toContain(expectedSnippet)
            expect(sent.query).toContain('{filters}')
            expect(sent.query).not.toContain('{tagger_id}')
            expect(sent.values).toBeUndefined()
        })
    })
})
