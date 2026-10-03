import type { Meta, StoryObj } from '@storybook/react'

import { NodeRawTab } from './NodeRawTab'

const meta: Meta<typeof NodeRawTab> = {
    title: 'Scenes-App/AI observability/Trace view/Raw event',
    component: NodeRawTab,
}
export default meta

export const Default: StoryObj<typeof NodeRawTab> = {
    args: {
        raw: {
            event: '$ai_generation',
            id: 'gen-answer',
            properties: { $ai_model: 'gpt-4.1-mini', $ai_latency: 1.88, $ai_input_tokens: 1822 },
        },
    },
}
