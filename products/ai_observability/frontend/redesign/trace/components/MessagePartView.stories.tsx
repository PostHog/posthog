import type { Meta, StoryObj } from '@storybook/react'

import {
    FIXTURE_ATTACHMENT_DATA_FILE,
    FIXTURE_ATTACHMENT_EXTERNAL_AUDIO,
    FIXTURE_ATTACHMENT_PARTS,
    FIXTURE_ATTACHMENT_REJECTED_IMAGE_URL,
    FIXTURE_ATTACHMENT_SAME_ORIGIN_AUDIO,
    withWidth,
} from '../storyFixtures'
import { MessagePart } from '../types'
import { MessagePartView } from './MessagePartView'

const meta: Meta<typeof MessagePartView> = {
    title: 'Scenes-App/AI observability/Trace view/Message part',
    component: MessagePartView,
}
export default meta

type Story = StoryObj<typeof MessagePartView>

export const Text: Story = { args: { part: { kind: 'text', text: 'Your team went from 4 to 6 seats.' } } }
export const Markdown: Story = {
    args: {
        part: {
            kind: 'text',
            text: '## Seat changes\n\n- **Before:** 4 seats\n- **After:** 6 seats\n\nSee `lookup_invoice` for the full breakdown.',
        },
    },
}
export const Thinking: Story = {
    args: { part: { kind: 'thinking', text: 'The user asks about invoices, check seats first.' } },
}
export const ToolCall: Story = {
    args: {
        part: {
            kind: 'toolCall',
            name: 'lookup_invoice',
            args: { month: '2026-08' },
            result: { total_usd: 180 },
        },
    },
}
export const ToolCallMultilineArgs: Story = {
    args: {
        part: {
            kind: 'toolCall',
            name: 'run_python',
            args: {
                language: 'python',
                code: 'def total(rows):\n    return sum(row["amount"] for row in rows)\n\nprint(total(invoice_rows))',
                timeout_s: 30,
            },
            result: { stdout: '180\n', exit_code: 0 },
        },
    },
}
const longResultPart: MessagePart = {
    kind: 'toolCall',
    name: 'lookup_seat_history',
    args: { team: 'team-42', months: 2 },
    result: {
        history: [
            { month: '2026-08', seats: 4, note: 'Seat count from the billing snapshot taken on the first day.' },
            { month: '2026-09', seats: 6, note: 'Two seats added mid-month, prorated on the next invoice.' },
        ],
    },
}
export const ToolCallLongResultFolded: Story = { args: { part: longResultPart }, decorators: [withWidth(420)] }
// A matching search query opens the fold without a click, so the snapshot does not depend on play timing.
export const ToolCallLongResultOpenWraps: Story = {
    args: { part: longResultPart, highlightQuery: '2026-09' },
    decorators: [withWidth(420)],
}
export const Attachments: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            {FIXTURE_ATTACHMENT_PARTS.map((part, index) => (
                <MessagePartView key={index} part={part} />
            ))}
        </div>
    ),
}
export const ExternalAudioChip: Story = { args: { part: FIXTURE_ATTACHMENT_EXTERNAL_AUDIO } }
export const SameOriginAudioPlayer: Story = { args: { part: FIXTURE_ATTACHMENT_SAME_ORIGIN_AUDIO } }
export const DataFileDownload: Story = { args: { part: FIXTURE_ATTACHMENT_DATA_FILE } }
export const RejectedImageUrlChip: Story = { args: { part: FIXTURE_ATTACHMENT_REJECTED_IMAGE_URL } }
