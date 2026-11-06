import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'
import { LLMTrace } from '~/queries/schema/schema-general'

import { TicketAiTracesList } from './TicketAiTracesList'

const PERSON_ID = '018f0000-0000-7000-8000-000000000001'

function trace(overrides: Partial<LLMTrace> & Pick<LLMTrace, 'id' | 'createdAt'>): LLMTrace {
    return { distinctId: 'customer-1', events: [], ...overrides }
}

function tracesResponse(results: LLMTrace[]): Record<string, unknown> {
    return { results, hasMore: false }
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
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': tracesResponse([
                    trace({
                        id: 'trace-checkout-assistant',
                        traceName: 'checkout_assistant',
                        createdAt: '2026-11-06T11:42:00Z',
                        totalCost: 0.0132,
                        errorCount: 2,
                    }),
                    trace({
                        id: 'trace-search',
                        traceName: 'product_search',
                        createdAt: '2026-11-05T09:10:00Z',
                        totalCost: 0.0021,
                    }),
                    trace({ id: '0193a0b1-unnamed-trace', createdAt: '2026-10-29T16:00:00Z' }),
                ]),
            },
        }),
    ],
}

export const NoTraces: Story = {
    decorators: [
        mswDecorator({
            post: { '/api/environments/:team_id/query/:kind/': tracesResponse([]) },
        }),
    ],
}
