import {
    COMPARISON_CONVERSATION_ID,
    COMPARISON_PANEL_ID,
    COMPARISON_RUN_ID,
    COMPARISON_TASK_ID,
    comparisonConversation,
    comparisonQueryResponse,
    comparisonRun,
    comparisonRunLogBody,
    comparisonTask,
} from './__mocks__/quillComparison.mocks'
import { MOCK_DEFAULT_BASIC_USER, MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { HttpResponse } from 'msw'
import { type ReactNode, useEffect, useState } from 'react'

import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { mswDecorator } from '~/mocks/browser'

import { type ThreadSkin, ThreadSkinOverrideContext } from 'products/posthog_ai/frontend/api/logics'
import { EmbeddedRunner } from 'products/posthog_ai/frontend/api/runner'

import conversationList from './__mocks__/conversationList.json'
import { AiFirstMaxInstance } from './components/AiFirstMaxInstance'
import { maxLogic } from './maxLogic'

/**
 * One investigation, three chats: the legacy chat as the flag-off majority sees it, the same chat in the quill
 * skin that `today-rail-nav` turns on, and the sandbox runner ("PostHog AI 2.0") in the same skin. The gaps
 * list under each quill column names what still renders in LemonUI there.
 */

async function queryHandler({ request }: { request: Request }): Promise<[number, Record<string, unknown>] | undefined> {
    const body = (await request.json()) as { query?: Record<string, unknown> }
    const response = body.query ? comparisonQueryResponse(body.query) : null
    return response ? [200, response] : undefined
}

const meta: Meta = {
    title: 'Scenes-App/PostHog AI/Quill comparison',
    decorators: [
        mswDecorator({
            get: {
                '/api/organizations/@current/': () => [
                    200,
                    { ...MOCK_DEFAULT_ORGANIZATION, is_ai_data_processing_approved: true },
                ],
                '/api/environments/:team_id/conversations/': () => [200, conversationList],
                [`/api/environments/:team_id/conversations/${COMPARISON_CONVERSATION_ID}/`]: () => [
                    200,
                    comparisonConversation(),
                ],
                '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
                '/api/projects/:team_id/tasks/': { count: 1, next: null, previous: null, results: [comparisonTask()] },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/tasks/@me/config/': { ai_run_preferences: {}, resolved_ai_run_defaults: {} },
                '/api/projects/:team_id/integrations/': { results: [] },
                [`/api/projects/:team_id/tasks/${COMPARISON_TASK_ID}/`]: comparisonTask(),
                [`/api/projects/:team_id/tasks/${COMPARISON_TASK_ID}/runs/`]: {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [comparisonRun()],
                },
                [`/api/projects/:team_id/tasks/${COMPARISON_TASK_ID}/runs/${COMPARISON_RUN_ID}/`]: comparisonRun(),
                [`/api/projects/:team_id/tasks/${COMPARISON_TASK_ID}/runs/${COMPARISON_RUN_ID}/logs`]: () =>
                    new HttpResponse(comparisonRunLogBody()),
                [`/api/projects/:team_id/tasks/${COMPARISON_TASK_ID}/runs/${COMPARISON_RUN_ID}/logs/`]: () =>
                    new HttpResponse(comparisonRunLogBody()),
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_BASIC_USER, is_staff: false }],
            },
            post: {
                '/api/environments/:team_id/query/': queryHandler,
                '/api/environments/:team_id/query/:kind/': queryHandler,
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-15T14:10:00Z',
        // Three live threads with charts: a snapshot of this page would be slow and flaky, and the story is a
        // review surface, not a regression gate.
        testOptions: { skip: true },
    },
}
export default meta

type Story = StoryObj<typeof meta>

const SHARED_GAPS = [
    'Context chips are LemonTags inside the quill composer',
    'The @-picker opens the Lemon taxonomic filter',
    'Insight charts and tables keep their Lemon controls',
]

const LEGACY_QUILL_GAPS = [
    ...SHARED_GAPS,
    'Feedback prompt, ticket prompt and approval card stay Lemon cards',
    'Notebook artifacts and the memory settings dialog stay Lemon',
    'Mode tooltips lose their tool lists in the quill menu',
    'Slash-command autocomplete is a Lemon menu',
]

const SANDBOX_QUILL_GAPS = [
    ...SHARED_GAPS,
    'No welcome header or suggestion row in the quill composer',
    'Plan card and permission card are Lemon inside the quill thread',
]

function Column({
    title,
    caption,
    gaps,
    skin,
    width,
    children,
}: {
    title: string
    caption: string
    gaps?: string[]
    skin: ThreadSkin
    width: number
    children: ReactNode
}): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <section className="flex shrink-0 flex-col gap-2" style={{ width }}>
            <header className="flex flex-col gap-1 px-1">
                <h2 className="m-0 text-base font-semibold">{title}</h2>
                <p className="m-0 text-xs text-secondary">{caption}</p>
            </header>
            <div className="flex h-[880px] flex-col overflow-hidden rounded border bg-surface-primary">
                <ThreadSkinOverrideContext.Provider value={skin}>{children}</ThreadSkinOverrideContext.Provider>
            </div>
            {gaps && gaps.length > 0 && (
                <details className="rounded border px-3 py-2 text-xs" open>
                    <summary className="cursor-pointer font-semibold">Still Lemon in this column</summary>
                    <ul className="mb-0 mt-1 list-disc pl-4 text-secondary">
                        {gaps.map((gap) => (
                            <li key={gap}>{gap}</li>
                        ))}
                    </ul>
                </details>
            )}
        </section>
    )
}

/** The legacy chat scene, pointed at the comparison conversation. Both legacy columns share one logic. */
function LegacyChat(): JSX.Element {
    const { setConversationId } = useActions(maxLogic({ panelId: COMPARISON_PANEL_ID }))
    useEffect(() => {
        setConversationId(COMPARISON_CONVERSATION_ID)
    }, [setConversationId])
    return <AiFirstMaxInstance tabId={COMPARISON_PANEL_ID} />
}

function SandboxChat(): JSX.Element {
    return (
        <div className="flex h-full min-h-0 flex-col">
            <EmbeddedRunner taskId={COMPARISON_TASK_ID} />
        </div>
    )
}

// Down to 320px, narrower than the side panel, so the narrow layouts can be checked here.
const MIN_COLUMN_WIDTH = 320
const MAX_COLUMN_WIDTH = 800

function SideBySideComparison(): JSX.Element {
    const [width, setWidth] = useState(600)
    return (
        <div className="flex flex-col gap-4 p-6">
            <div className="flex w-[480px] items-center gap-3 text-xs">
                <span className="shrink-0 font-semibold">Column width</span>
                <LemonSlider
                    value={width}
                    onChange={setWidth}
                    min={MIN_COLUMN_WIDTH}
                    max={MAX_COLUMN_WIDTH}
                    step={10}
                    className="flex-1"
                />
                <span className="w-12 shrink-0 text-right tabular-nums">{width}px</span>
            </div>
            <div className="flex items-start gap-6 overflow-x-auto">
                <Column
                    title="PostHog AI now"
                    caption="Flag off, the majority today: the LangGraph conversation in LemonUI."
                    skin="lemon"
                    width={width}
                >
                    <LegacyChat />
                </Column>
                <Column
                    title="PostHog AI quill"
                    caption="phai-quill or today-rail-nav on: the same LangGraph conversation in the quill skin."
                    gaps={LEGACY_QUILL_GAPS}
                    skin="quill"
                    width={width}
                >
                    <LegacyChat />
                </Column>
                <Column
                    title="PostHog AI 2.0 quill"
                    caption="phai-sandbox-mode and today-rail-nav on: the sandbox runner in the quill skin."
                    gaps={SANDBOX_QUILL_GAPS}
                    skin="quill"
                    width={width}
                >
                    <SandboxChat />
                </Column>
            </div>
        </div>
    )
}

export const SideBySide: Story = {
    render: () => <SideBySideComparison />,
}
