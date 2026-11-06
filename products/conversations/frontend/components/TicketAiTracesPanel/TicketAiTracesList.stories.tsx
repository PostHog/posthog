import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/react'

import { mswDecorator } from '~/mocks/browser'
import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { TicketAiTracesList } from './TicketAiTracesList'

const PERSON_ID = '018f0000-0000-7000-8000-000000000001'
const TRACE_ID = 'trace-checkout-assistant'

function trace(overrides: Partial<LLMTrace> & Pick<LLMTrace, 'id' | 'createdAt'>): LLMTrace {
    return { distinctId: 'customer-1', events: [], ...overrides }
}

function generation(id: string, createdAt: string, properties: Record<string, any>): LLMTraceEvent {
    return {
        id,
        event: '$ai_generation',
        createdAt,
        properties: { $ai_trace_id: TRACE_ID, $ai_model: 'gpt-4.1-mini', $ai_provider: 'openai', ...properties },
    }
}

const TRACES: LLMTrace[] = [
    trace({
        id: TRACE_ID,
        traceName: 'checkout_assistant',
        createdAt: '2026-11-06T11:42:00Z',
        totalCost: 0.0132,
        errorCount: 1,
    }),
    trace({ id: 'trace-search', traceName: 'product_search', createdAt: '2026-11-05T09:10:00Z', totalCost: 0.0021 }),
    trace({ id: '0193a0b1-unnamed-trace', createdAt: '2026-10-29T16:00:00Z' }),
]

const EXPANDED_TRACE: LLMTrace = {
    ...TRACES[0],
    events: [
        generation('generation-failed', '2026-11-06T11:42:01Z', {
            $ai_input: [{ role: 'user', content: 'Why was my card declined at checkout?' }],
            $ai_error: 'Request timed out',
            $ai_is_error: true,
            $ai_http_status: 504,
        }),
        generation('generation-answer', '2026-11-06T11:42:09Z', {
            $ai_input: [
                { role: 'system', content: 'You help customers finish checking out.' },
                { role: 'user', content: 'Why was my card declined at checkout?' },
            ],
            $ai_output_choices: [
                {
                    role: 'assistant',
                    content: 'Your bank declined the payment. Try another card, or ask your bank to approve it.',
                },
            ],
            $ai_input_tokens: 820,
            $ai_output_tokens: 140,
            $ai_latency: 1.1,
            $ai_total_cost_usd: 0.0044,
        }),
    ],
}

function queryHandler(traces: LLMTrace[]) {
    return async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
        const body = (await request.json()) as { query?: { kind?: string } }
        if (body.query?.kind === 'TraceQuery') {
            return [200, { results: [EXPANDED_TRACE] }]
        }
        return [200, { results: traces, hasMore: false }]
    }
}

const meta: Meta<typeof TicketAiTracesList> = {
    title: 'Scenes-App/Support/TicketAiTracesList',
    component: TicketAiTracesList,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2026-11-06T12:00:00Z',
        testOptions: { snapshotBrowsers: [] },
    },
    render: () => (
        // The sidebar's minimum width next to the chat.
        <div className="w-[300px]">
            <TicketAiTracesList personId={PERSON_ID} />
        </div>
    ),
}
export default meta

type Story = StoryObj<typeof TicketAiTracesList>

export const WithTraces: Story = {
    decorators: [mswDecorator({ post: { '/api/environments/:team_id/query/:kind/': queryHandler(TRACES) } })],
}

export const ExpandedTrace: Story = {
    decorators: [mswDecorator({ post: { '/api/environments/:team_id/query/:kind/': queryHandler(TRACES) } })],
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        fireEvent.click(await canvas.findByText('checkout_assistant'))
        await canvas.findByText(/Your bank declined the payment/)
    },
}

export const NoTraces: Story = {
    decorators: [mswDecorator({ post: { '/api/environments/:team_id/query/:kind/': queryHandler([]) } })],
}
