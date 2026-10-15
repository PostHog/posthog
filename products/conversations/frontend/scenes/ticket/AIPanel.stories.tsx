import type { Meta, StoryObj } from '@storybook/react'

import type { AITriage } from '../../types'
import { AIPanel } from './AIPanel'

const meta: Meta<typeof AIPanel> = {
    title: 'Scenes-App/Support/AIPanel',
    component: AIPanel,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof AIPanel>

const sdkSource = {
    ref: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
    title: 'Install the JavaScript SDK',
    source_id: '11111111-1111-1111-1111-111111111111',
    url: null,
    is_generated: false,
    learned_from_ticket_number: null,
}

const learnedSource = {
    ref: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
    title: 'Refund policy',
    source_id: '22222222-2222-2222-2222-222222222222',
    url: null,
    is_generated: true,
    learned_from_ticket_number: 42,
}

const docsSource = {
    ref: 'https://example.com/docs/sdk',
    title: 'example.com/docs/sdk',
    source_id: null,
    url: 'https://example.com/docs/sdk',
    is_generated: false,
    learned_from_ticket_number: null,
}

function triage(overrides: AITriage): AITriage {
    return {
        ticket_type: 'how_to',
        confidence: 0.9,
        attempts: 1,
        started_at: '2026-09-21T12:00:00Z',
        finished_at: '2026-09-21T12:01:00Z',
        ...overrides,
    }
}

function Narrow({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="w-[520px]">{children}</div>
}

export const AutoSent: Story = {
    render: () => (
        <Narrow>
            <AIPanel
                aiTriage={triage({
                    status: 'done',
                    result: 'persisted',
                    verdict: 'answerable',
                    blocker: 'none',
                    confidence: 0.92,
                    sources: [sdkSource, docsSource],
                })}
            />
        </Narrow>
    ),
}

export const Suggested: Story = {
    render: () => (
        <Narrow>
            <AIPanel
                aiTriage={triage({
                    status: 'done',
                    result: 'suggested',
                    verdict: 'answerable',
                    blocker: 'none',
                    confidence: 0.64,
                    investigation_summary: 'Docs cover snippet install. The ticket did not say which pages.',
                    unknowns: ['Which pages should get the snippet'],
                    sources: [sdkSource],
                })}
            />
        </Narrow>
    ),
}

export const FindingsOnly: Story = {
    render: () => (
        <Narrow>
            <AIPanel
                aiTriage={triage({
                    status: 'done',
                    result: 'escalated_with_findings',
                    verdict: 'blocked_on_knowledge',
                    blocker: 'knowledge',
                    confidence: 0.31,
                    investigation_summary: 'Searched team docs and learned sources. No matching procedure.',
                    unknowns: ['How this team handles SSO timeouts'],
                    missing: ['SSO timeout runbook'],
                    sources: [learnedSource],
                })}
            />
        </Narrow>
    ),
}

export const AwaitingClarification: Story = {
    render: () => (
        <Narrow>
            <AIPanel
                aiTriage={triage({
                    status: 'awaiting_clarification',
                    result: 'clarified',
                    verdict: 'blocked_on_customer',
                    blocker: 'customer_info',
                    confidence: 0.4,
                    investigation_summary: 'Need the SDK name before answering.',
                    unknowns: ['Which SDK the customer is using'],
                    sources: [sdkSource],
                })}
            />
        </Narrow>
    ),
}
