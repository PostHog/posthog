import type { Meta, StoryObj } from '@storybook/react'

import { MessagePartView } from './MessagePartView'

const meta: Meta<typeof MessagePartView> = {
    title: 'Scenes-App/AI observability/Trace view/Message part',
    component: MessagePartView,
}
export default meta

type Story = StoryObj<typeof MessagePartView>

export const Text: Story = { args: { part: { kind: 'text', text: 'Your team went from 4 to 6 seats.' } } }
export const Thinking: Story = {
    args: { part: { kind: 'thinking', text: 'The user asks about invoices, check seats first.' } },
}
export const ToolCall: Story = {
    args: {
        part: { kind: 'toolCall', name: 'lookup_invoice', args: { month: '2026-08' }, result: { total_usd: 180 } },
    },
}
export const ToolCallError: Story = {
    args: {
        part: {
            kind: 'toolCall',
            name: 'lookup_invoice',
            args: { month: '2026-08' },
            result: 'Timeout',
            isError: true,
        },
    },
}
export const Attachment: Story = { args: { part: { kind: 'attachment', label: 'image/png' } } }
