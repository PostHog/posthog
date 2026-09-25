import type { Meta, StoryObj } from '@storybook/react'

import { NodePropertyList } from './NodePropertyList'

const meta: Meta<typeof NodePropertyList> = {
    title: 'Scenes-App/AI observability/Trace view/Node properties',
    component: NodePropertyList,
}
export default meta

type Story = StoryObj<typeof NodePropertyList>

export const Generation: Story = {
    args: {
        properties: {
            timestamp: '2026-09-01T10:15:02Z',
            model: 'gpt-4.1-mini',
            provider: 'openai',
            temperature: 0.2,
            sessionId: 'sess-7f3a',
            promptName: 'billing-answer',
            promptVersion: 6,
        },
    },
}
export const Span: Story = {
    args: {
        properties: {
            timestamp: '2026-09-01T10:15:00Z',
            model: null,
            provider: null,
            temperature: null,
            sessionId: null,
            promptName: null,
            promptVersion: null,
        },
    },
}
