import { RenderResult, act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { performQuery } from '~/queries/query'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { llmPromptsResolveNameRetrieve } from '../generated/api'
import type { LLMPromptResolveResponseApi } from '../generated/api.schemas'
import { llmPromptLogic } from './llmPromptLogic'
import { PromptRelatedTraces } from './promptSceneComponents'

jest.mock('../generated/api', () => ({ llmPromptsResolveNameRetrieve: jest.fn() }))
jest.mock('~/queries/query', () => ({ ...jest.requireActual('~/queries/query'), performQuery: jest.fn() }))

const PROMPT_NAME = 'my-test-prompt'
const PATH = `/prompt-management/prompts/${PROMPT_NAME}`
const TRACES = [
    { id: 'trace-1', createdAt: '2026-01-01T12:00:00Z', events: [], traceName: 'first' },
    { id: 'trace-2', createdAt: '2026-01-01T13:00:00Z', events: [], traceName: 'second' },
]

function tracesRequests(): number {
    return jest.mocked(performQuery).mock.calls.filter(([query]) => query.kind === NodeKind.TracesQuery).length
}

describe('PromptRelatedTraces', () => {
    let logic: ReturnType<typeof llmPromptLogic.build>

    async function renderList(): Promise<RenderResult> {
        initKeaTests()
        localStorage.clear()
        jest.mocked(llmPromptsResolveNameRetrieve).mockResolvedValue({
            prompt: {
                id: 'prompt-1',
                name: PROMPT_NAME,
                prompt: 'You are a helpful assistant.',
                version: 2,
                latest_version: 2,
                version_count: 1,
                is_latest: true,
                deleted: false,
                created_at: '2024-01-02T00:00:00Z',
                updated_at: '2024-01-02T00:00:00Z',
            },
            versions: [],
            has_more: false,
        } as unknown as LLMPromptResolveResponseApi)
        jest.mocked(performQuery).mockReset()
        jest.mocked(performQuery).mockImplementation(async (query) =>
            query.kind === NodeKind.TracesQuery ? { results: TRACES } : { results: [] }
        )
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN], {
            [FEATURE_FLAGS.AI_OBSERVABILITY_TRACE_REDESIGN]: true,
        })
        panelLayoutLogic.mount()
        router.actions.push(PATH, { tab: 'usage' })
        logic = llmPromptLogic({ promptName: PROMPT_NAME })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])
        const view = render(
            <BindLogic logic={llmPromptLogic} props={{ promptName: PROMPT_NAME }}>
                <PromptRelatedTraces />
            </BindLogic>
        )
        await waitFor(() => expect(view.container.querySelector('[data-attr="trace-id-link"]')).not.toBeNull())
        return view
    }

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it.each([
        ['the row', (view: RenderResult): Element | null => view.getByText('first').closest('tr')?.children[1] ?? null],
        [
            'the ID link',
            (view: RenderResult): Element | null => view.container.querySelector('[data-attr="trace-id-link"]'),
        ],
    ])('opens the drawer from %s and stays on the usage tab', async (_name, target) => {
        const view = await renderList()
        const clicked = target(view)
        if (!clicked) {
            throw new Error('No click target')
        }

        fireEvent.click(clicked)

        expect(router.values.location.pathname).toContain(PATH)
        expect(router.values.searchParams).toMatchObject({ tab: 'usage', trace: 'trace-1' })
    })

    it('does not refetch the traces when the prompt reloads', async () => {
        await renderList()
        expect(tracesRequests()).toBe(1)

        await act(async () => {
            logic.actions.loadPrompt()
            await expectLogic(logic).toDispatchActions(['loadPromptSuccess'])
        })

        expect(tracesRequests()).toBe(1)
    })
})
